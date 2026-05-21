"""Temporal worker — run with: uv run python -m film.temporal.worker"""
import asyncio

import structlog
from temporalio.worker import Worker

from film.activities.finalize import mark_completed
from film.activities.research import research_topic
from film.activities.script import generate_script
from film.core.config import get_settings
from film.core.logging import setup_logging
from film.temporal.client import get_temporal_client
from film.workflows.production import FilmProductionWorkflow

logger = structlog.get_logger()


async def run_worker() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.environment)

    client = await get_temporal_client()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[FilmProductionWorkflow],
        activities=[research_topic, generate_script, mark_completed],
    )
    logger.info("temporal_worker_started", task_queue=settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
