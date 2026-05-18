"""Temporal worker entry point.

Run with: uv run python -m film.temporal.worker
Activities and workflows will be registered here in Phase 2+.
"""
import asyncio

import structlog
from temporalio.worker import Worker

from film.core.config import get_settings
from film.core.logging import setup_logging
from film.temporal.client import get_temporal_client

logger = structlog.get_logger()


async def run_worker() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.environment)

    client = await get_temporal_client()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[],   # Phase 2: add FilmProductionWorkflow
        activities=[],  # Phase 2: add research_topic, generate_script, etc.
    )
    logger.info("temporal_worker_started", task_queue=settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
