"""Asset generation activity — voiceover via ElevenLabs, images via Pollinations.ai."""
import io
import re
import uuid
from dataclasses import dataclass

import httpx
import structlog
from elevenlabs.client import AsyncElevenLabs
from sqlalchemy import select
from temporalio import activity

from film.core.config import get_settings
from film.db.models import AIUsage, Asset, Project
from film.db.session import AsyncSessionFactory
from film.storage import upload_bytes

logger = structlog.get_logger()


@dataclass
class AssetsInput:
    project_id: str
    topic: str
    tone: str


@dataclass
class AssetsOutput:
    voiceovers_generated: int
    images_generated: int
    total_assets: int


def _extract_narrations(script_text: str) -> list[dict]:
    """Extract NARRATION blocks from the script."""
    scenes = []
    scene_blocks = re.split(r'SCENE \d+[:\s]', script_text)

    for i, block in enumerate(scene_blocks[1:], start=1):
        narration_match = re.search(r'NARRATION:\s*\n(.*?)(?=VISUALS:|TRANSITION:|SCENE \d+|$)', block, re.DOTALL)
        narration = ""
        if narration_match:
            narration = narration_match.group(1).strip().strip('"').strip("'")

        visuals_match = re.search(r'VISUALS:\s*\n(.*?)(?=TRANSITION:|SCENE \d+|$)', block, re.DOTALL)
        visuals = ""
        if visuals_match:
            visuals = visuals_match.group(1).strip()

        if narration or visuals:
            scenes.append({
                "scene_number": i,
                "narration": narration[:500] if narration else f"Scene {i} of the documentary.",
                "visuals": visuals[:300] if visuals else "",
            })

    return scenes


async def _generate_voiceover(narration: str, scene_num: int, project_id: uuid.UUID, settings) -> str | None:
    """Call ElevenLabs TTS and upload MP3 to MinIO. Returns storage URL."""
    try:
        client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        # convert() returns an async generator directly — iterate it
        audio_chunks = []
        async for chunk in client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            text=narration,
            model_id="eleven_turbo_v2",
            output_format="mp3_44100_128",
        ):
            audio_chunks.append(chunk)
        audio_bytes = b"".join(audio_chunks)
        key = f"{project_id}/audio/scene_{scene_num:02d}.mp3"
        url = await upload_bytes(audio_bytes, key, content_type="audio/mpeg")
        return url
    except Exception as e:
        logger.warning("voiceover_failed", scene=scene_num, error=str(e))
        return None


async def _generate_image(visuals: str, topic: str, tone: str, scene_num: int, project_id: uuid.UUID) -> str | None:
    """Call Pollinations.ai (free, no key needed) and upload image to MinIO."""
    try:
        prompt = f"{tone} documentary style, {topic}, {visuals[:200]}, cinematic, high quality"
        prompt_encoded = prompt.replace(" ", "%20")[:500]
        url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1280&height=720&nologo=true"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None
            image_bytes = response.content

        key = f"{project_id}/images/scene_{scene_num:02d}.jpg"
        storage_url = await upload_bytes(image_bytes, key, content_type="image/jpeg")
        return storage_url
    except Exception as e:
        logger.warning("image_generation_failed", scene=scene_num, error=str(e))
        return None


@activity.defn(name="generate_assets")
async def generate_assets(inp: AssetsInput) -> AssetsOutput:
    settings = get_settings()
    project_id = uuid.UUID(inp.project_id)
    log = logger.bind(project_id=inp.project_id, topic=inp.topic)
    log.info("asset_generation_started")

    # Mark project as generating assets
    async with AsyncSessionFactory() as db:
        project = await db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        project.status = "generating_assets"
        project.current_phase = "Generating Assets"
        project.progress = 65
        await db.commit()

    # Fetch script
    async with AsyncSessionFactory() as db:
        script_asset = (
            await db.execute(
                select(Asset)
                .where(Asset.project_id == project_id, Asset.type == "script")
                .order_by(Asset.created_at.desc())
            )
        ).scalars().first()

    if not script_asset or not script_asset.meta or not script_asset.meta.get("content"):
        raise ValueError(f"No script found for project {project_id}")

    script_text = script_asset.meta["content"]
    scenes = _extract_narrations(script_text)

    if not scenes:
        raise ValueError(f"Could not parse narrations from script for project {project_id}")

    log.info("scenes_to_process", count=len(scenes))

    voiceovers = 0
    images = 0

    for scene in scenes:
        scene_num = scene["scene_number"]

        # Generate voiceover
        if scene["narration"]:
            log.info("generating_voiceover", scene=scene_num)
            audio_url = await _generate_voiceover(
                scene["narration"], scene_num, project_id, settings
            )
            if audio_url:
                async with AsyncSessionFactory() as db:
                    db.add(Asset(
                        project_id=project_id,
                        type="voiceover",
                        scene_number=scene_num,
                        storage_url=audio_url,
                        meta={"narration": scene["narration"]},
                    ))
                    db.add(AIUsage(
                        project_id=project_id,
                        provider="elevenlabs",
                        model="eleven_turbo_v2",
                        operation=f"tts_scene_{scene_num}",
                        input_tokens=len(scene["narration"].split()),
                        output_tokens=0,
                        cost=None,
                    ))
                    await db.commit()
                voiceovers += 1
                log.info("voiceover_saved", scene=scene_num, url=audio_url)

        # Generate image via Pollinations.ai
        if scene["visuals"]:
            log.info("generating_image", scene=scene_num)
            image_url = await _generate_image(
                scene["visuals"], inp.topic, inp.tone, scene_num, project_id
            )
            if image_url:
                async with AsyncSessionFactory() as db:
                    db.add(Asset(
                        project_id=project_id,
                        type="scene_image",
                        scene_number=scene_num,
                        storage_url=image_url,
                        meta={"visuals_prompt": scene["visuals"]},
                    ))
                    await db.commit()
                images += 1
                log.info("image_saved", scene=scene_num, url=image_url)

    # Update progress to 80%
    async with AsyncSessionFactory() as db:
        project = await db.get(Project, project_id)
        project.progress = 80
        project.current_phase = "Generating Assets"
        await db.commit()

    log.info("asset_generation_complete", voiceovers=voiceovers, images=images)
    return AssetsOutput(
        voiceovers_generated=voiceovers,
        images_generated=images,
        total_assets=voiceovers + images,
    )
