"""Research activity — calls Groq to research a topic, stores chunks with embeddings."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from groq import AsyncGroq
from sentence_transformers import SentenceTransformer
from temporalio import activity

from film.core.config import get_settings
from film.db.models import AIUsage, Project, ResearchChunk
from film.db.session import AsyncSessionFactory

logger = structlog.get_logger()

_embed_model: SentenceTransformer | None = None


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


@dataclass
class ResearchInput:
    project_id: str
    topic: str
    duration_minutes: int
    tone: str


@dataclass
class ResearchOutput:
    chunks_stored: int
    total_tokens: int


RESEARCH_PROMPT = """\
You are a documentary researcher. Research the following topic thoroughly for a {duration}-minute {tone} documentary.

Topic: {topic}

Provide a comprehensive research report with:
1. Historical background and context
2. Key events and timeline
3. Important figures involved
4. Causes and effects
5. Different perspectives and controversies
6. Lasting impact and legacy
7. Interesting facts and lesser-known details

Write in clear, factual prose. Be detailed and thorough — this will form the foundation of a documentary script.
"""


@activity.defn(name="research_topic")
async def research_topic(inp: ResearchInput) -> ResearchOutput:
    settings = get_settings()
    project_id = uuid.UUID(inp.project_id)

    log = logger.bind(project_id=inp.project_id, topic=inp.topic)
    log.info("research_started")

    async with AsyncSessionFactory() as db:
        # Mark project as researching
        project = await db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        project.status = "researching"
        project.current_phase = "Research & Analysis"
        project.progress = 5
        await db.commit()

    # Call Groq
    client = AsyncGroq(api_key=settings.groq_api_key)
    prompt = RESEARCH_PROMPT.format(
        topic=inp.topic,
        duration=inp.duration_minutes,
        tone=inp.tone or "documentary",
    )

    log.info("calling_groq", model=settings.groq_model)
    response = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4096,
    )

    research_text = response.choices[0].message.content or ""
    usage = response.usage
    total_tokens = (usage.prompt_tokens + usage.completion_tokens) if usage else 0

    log.info("groq_response_received", tokens=total_tokens, chars=len(research_text))

    # Split into chunks (~500 chars each, on paragraph boundaries)
    paragraphs = [p.strip() for p in research_text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) < 600:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)

    # Generate embeddings (all-MiniLM-L6-v2 outputs 384 dims — stored as-is, vector col is flexible)
    embed_model = _get_embed_model()
    embeddings = embed_model.encode(chunks, normalize_embeddings=True).tolist()

    # Store chunks + log AI usage
    async with AsyncSessionFactory() as db:
        for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(ResearchChunk(
                project_id=project_id,
                content=chunk_text,
                embedding=embedding,
                meta={"chunk_index": i, "source": "groq_research"},
            ))

        db.add(AIUsage(
            project_id=project_id,
            provider="groq",
            model=settings.groq_model,
            operation="research",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cost=None,  # Groq free tier — no cost tracking needed
        ))

        # Advance progress to 20%
        project = await db.get(Project, project_id)
        project.status = "researching"
        project.progress = 20
        project.current_phase = "Research & Analysis"
        await db.commit()

    log.info("research_complete", chunks=len(chunks), tokens=total_tokens)
    return ResearchOutput(chunks_stored=len(chunks), total_tokens=total_tokens)
