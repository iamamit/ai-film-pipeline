"""Storyboard generation activity — uses RAG to generate visual shot descriptions per scene."""
import re
import uuid
from dataclasses import dataclass

import structlog
from groq import AsyncGroq
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, text
from temporalio import activity

from film.core.config import get_settings
from film.db.models import AIUsage, Asset, Project, ResearchChunk
from film.db.session import AsyncSessionFactory

logger = structlog.get_logger()

_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


@dataclass
class StoryboardInput:
    project_id: str
    topic: str
    tone: str


@dataclass
class StoryboardOutput:
    scenes_processed: int
    total_tokens: int
    asset_id: str


STORYBOARD_PROMPT = """\
You are a visual director for a {tone} documentary about: {topic}

SCENE TO VISUALIZE:
{scene_text}

RELEVANT RESEARCH CONTEXT:
{research_context}

---

Create a detailed storyboard for this scene. Use this exact format:

VISUAL STYLE: [Overall look — lighting, color palette, mood]

SHOT 1:
  Type: [Wide/Medium/Close-up/Extreme close-up/Aerial]
  Subject: [What's in frame]
  Camera: [Static/Pan/Tilt/Dolly/Handheld]
  Description: [What the viewer sees]
  Duration: [seconds]

SHOT 2:
  [same format]

SHOT 3:
  [same format]

SOUND DESIGN: [Ambient sounds, music mood, any specific audio cues]
TRANSITION TO NEXT SCENE: [Hard cut / Dissolve / Fade to black / Match cut]
"""


def _parse_scenes_from_script(script_text: str) -> list[dict]:
    """Extract individual scenes from the generated script."""
    scenes = []
    # Split on SCENE N: pattern
    parts = re.split(r'(SCENE \d+[:\s])', script_text)

    current_scene_num = None
    current_content = []

    for part in parts:
        scene_match = re.match(r'SCENE (\d+)[:\s]', part)
        if scene_match:
            if current_scene_num is not None and current_content:
                scenes.append({
                    "number": current_scene_num,
                    "text": "".join(current_content).strip(),
                })
            current_scene_num = int(scene_match.group(1))
            current_content = []
        else:
            if current_scene_num is not None:
                current_content.append(part)

    if current_scene_num is not None and current_content:
        scenes.append({
            "number": current_scene_num,
            "text": "".join(current_content).strip(),
        })

    return scenes


async def _rag_fetch(project_id: uuid.UUID, query: str, top_k: int = 4) -> str:
    """RAG: embed the query, find top-K most similar research chunks via pgvector."""
    embed_model = _get_embed_model()
    query_embedding = embed_model.encode(query, normalize_embeddings=True).tolist()

    async with AsyncSessionFactory() as db:
        # pgvector cosine distance operator <=>
        rows = await db.execute(
            text("""
                SELECT content
                FROM research_chunks
                WHERE project_id = :project_id
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """),
            {
                "project_id": str(project_id),
                "embedding": str(query_embedding),
                "top_k": top_k,
            },
        )
        chunks = [row[0] for row in rows if row[0]]

    return "\n\n---\n\n".join(chunks) if chunks else "No relevant research found."


@activity.defn(name="generate_storyboard")
async def generate_storyboard(inp: StoryboardInput) -> StoryboardOutput:
    settings = get_settings()
    project_id = uuid.UUID(inp.project_id)
    log = logger.bind(project_id=inp.project_id, topic=inp.topic)
    log.info("storyboard_generation_started")

    # Mark project as storyboarding
    async with AsyncSessionFactory() as db:
        project = await db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        project.status = "storyboarding"
        project.current_phase = "Storyboarding"
        project.progress = 45
        await db.commit()

    # Fetch the script asset
    async with AsyncSessionFactory() as db:
        asset = (
            await db.execute(
                select(Asset)
                .where(Asset.project_id == project_id, Asset.type == "script")
                .order_by(Asset.created_at.desc())
            )
        ).scalars().first()

    if not asset or not asset.meta or not asset.meta.get("content"):
        raise ValueError(f"No script found for project {project_id}")

    script_text = asset.meta["content"]
    scenes = _parse_scenes_from_script(script_text)

    if not scenes:
        raise ValueError(f"Could not parse scenes from script for project {project_id}")

    log.info("scenes_parsed", count=len(scenes))

    # Generate storyboard for each scene using RAG
    client = AsyncGroq(api_key=settings.groq_api_key)
    storyboard_scenes = []
    total_tokens = 0

    for scene in scenes:
        scene_text = scene["text"][:800]  # trim per-scene context

        # RAG: find the most relevant research chunks for this specific scene
        research_context = await _rag_fetch(project_id, query=scene_text, top_k=4)
        log.info("rag_fetch_done", scene=scene["number"], context_chars=len(research_context))

        prompt = STORYBOARD_PROMPT.format(
            topic=inp.topic,
            tone=inp.tone or "documentary",
            scene_text=scene_text,
            research_context=research_context[:2000],
        )

        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1024,
        )

        storyboard_text = response.choices[0].message.content or ""
        usage = response.usage
        total_tokens += (usage.prompt_tokens + usage.completion_tokens) if usage else 0

        storyboard_scenes.append({
            "scene_number": scene["number"],
            "scene_text": scene_text,
            "storyboard": storyboard_text,
        })

        # Log AI usage per scene
        async with AsyncSessionFactory() as db:
            db.add(AIUsage(
                project_id=project_id,
                provider="groq",
                model=settings.groq_model,
                operation=f"storyboard_scene_{scene['number']}",
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                cost=None,
            ))
            await db.commit()

    # Store full storyboard as Asset
    asset_id = uuid.uuid4()
    async with AsyncSessionFactory() as db:
        db.add(Asset(
            id=asset_id,
            project_id=project_id,
            type="storyboard",
            scene_number=None,
            storage_url=None,
            meta={
                "scenes": storyboard_scenes,
                "total_scenes": len(storyboard_scenes),
                "topic": inp.topic,
            },
        ))

        project = await db.get(Project, project_id)
        project.progress = 60
        project.current_phase = "Storyboarding"
        await db.commit()

    log.info("storyboard_complete", scenes=len(storyboard_scenes), tokens=total_tokens)
    return StoryboardOutput(
        scenes_processed=len(storyboard_scenes),
        total_tokens=total_tokens,
        asset_id=str(asset_id),
    )
