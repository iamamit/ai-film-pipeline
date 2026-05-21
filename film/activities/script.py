"""Script generation activity — turns research chunks into a full documentary script."""
import uuid
from dataclasses import dataclass

import structlog
from groq import AsyncGroq
from sqlalchemy import select
from temporalio import activity

from film.core.config import get_settings
from film.db.models import AIUsage, Asset, Project, ResearchChunk
from film.db.session import AsyncSessionFactory

logger = structlog.get_logger()


@dataclass
class ScriptInput:
    project_id: str
    topic: str
    duration_minutes: int
    tone: str


@dataclass
class ScriptOutput:
    scenes: int
    total_tokens: int
    asset_id: str


SCRIPT_PROMPT = """\
You are an award-winning documentary scriptwriter. Using the research below, write a complete \
{duration}-minute {tone} documentary script about: {topic}

RESEARCH:
{research}

---

Write a full shooting script with this structure:

TITLE: [Documentary Title]
LOGLINE: [One sentence summary]

ACT 1 - OPENING (scenes 1-2)
ACT 2 - MAIN NARRATIVE (scenes 3-{mid_scene})
ACT 3 - CONCLUSION (scenes {end_scene}-{total_scenes})

For each scene use this exact format:

SCENE [N]: [SCENE TITLE]
LOCATION: [Setting]
DURATION: [X minutes]
NARRATION:
[Narration text spoken by documentary narrator]
VISUALS:
[Description of what appears on screen — archival footage, graphics, interviews, b-roll]
TRANSITION: [Cut to / Fade / Dissolve]

---

Write all {total_scenes} scenes. Be cinematic, engaging, and factually grounded in the research.
"""


def _estimate_scenes(duration_minutes: int) -> tuple[int, int, int]:
    """Returns (total_scenes, mid_scene, end_scene)."""
    total = max(4, duration_minutes // 2)
    mid = total // 2
    end = total - 1
    return total, mid, end


@activity.defn(name="generate_script")
async def generate_script(inp: ScriptInput) -> ScriptOutput:
    settings = get_settings()
    project_id = uuid.UUID(inp.project_id)
    log = logger.bind(project_id=inp.project_id, topic=inp.topic)
    log.info("script_generation_started")

    # Mark project as scripting
    async with AsyncSessionFactory() as db:
        project = await db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        project.status = "scripting"
        project.current_phase = "Script Writing"
        project.progress = 25
        await db.commit()

    # Fetch research chunks from DB
    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(ResearchChunk)
                .where(ResearchChunk.project_id == project_id)
                .order_by(ResearchChunk.created_at)
            )
        ).scalars().all()

    if not rows:
        raise ValueError(f"No research chunks found for project {project_id}")

    research_text = "\n\n".join(r.content for r in rows if r.content)
    # Trim to avoid hitting context limits (~6000 chars is plenty for context)
    if len(research_text) > 6000:
        research_text = research_text[:6000] + "\n\n[...research continues...]"

    total_scenes, mid_scene, end_scene = _estimate_scenes(inp.duration_minutes)

    prompt = SCRIPT_PROMPT.format(
        topic=inp.topic,
        duration=inp.duration_minutes,
        tone=inp.tone or "documentary",
        research=research_text,
        total_scenes=total_scenes,
        mid_scene=mid_scene,
        end_scene=end_scene,
    )

    log.info("calling_groq_for_script", model=settings.groq_model, scenes=total_scenes)

    client = AsyncGroq(api_key=settings.groq_api_key)
    response = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=4096,
    )

    script_text = response.choices[0].message.content or ""
    usage = response.usage
    total_tokens = (usage.prompt_tokens + usage.completion_tokens) if usage else 0

    # Count scenes in output
    scenes_written = script_text.count("SCENE ")
    log.info("script_received", tokens=total_tokens, scenes=scenes_written, chars=len(script_text))

    # Store script as an Asset + log AI usage
    asset_id = uuid.uuid4()
    async with AsyncSessionFactory() as db:
        db.add(Asset(
            id=asset_id,
            project_id=project_id,
            type="script",
            scene_number=None,
            storage_url=None,
            meta={
                "content": script_text,
                "scenes": scenes_written,
                "duration_minutes": inp.duration_minutes,
                "tone": inp.tone,
            },
        ))

        db.add(AIUsage(
            project_id=project_id,
            provider="groq",
            model=settings.groq_model,
            operation="script_generation",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cost=None,
        ))

        project = await db.get(Project, project_id)
        project.progress = 40
        project.current_phase = "Script Writing"
        await db.commit()

    log.info("script_complete", scenes=scenes_written, tokens=total_tokens)
    return ScriptOutput(scenes=scenes_written, total_tokens=total_tokens, asset_id=str(asset_id))
