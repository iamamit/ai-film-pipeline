"""Finalize activity — marks project completed after all phases are done."""
import uuid
from datetime import datetime, timezone

import structlog
from temporalio import activity

from film.db.models import Project
from film.db.session import AsyncSessionFactory

logger = structlog.get_logger()


@activity.defn(name="mark_completed")
async def mark_completed(project_id: str) -> None:
    async with AsyncSessionFactory() as db:
        project = await db.get(Project, uuid.UUID(project_id))
        if not project:
            raise ValueError(f"Project {project_id} not found")
        project.status = "completed"
        project.progress = 100
        project.current_phase = None
        project.completed_at = datetime.now(timezone.utc)
        await db.commit()
    logger.info("project_completed", project_id=project_id)
