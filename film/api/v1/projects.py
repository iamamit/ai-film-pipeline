import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from film.api.deps import CurrentUser, DbSession
from film.db.models import Project
from film.schemas.project import ProjectCreate, ProjectListResponse, ProjectResponse
from film.temporal.client import get_temporal_client
from film.workflows.production import FilmProductionWorkflow, ProductionInput

logger = structlog.get_logger()
router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> Project:
    project = Project(
        user_id=user_id,
        topic=data.topic,
        duration_minutes=data.duration_minutes,
        tone=data.tone,
        status="pending",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    logger.info("project_created", project_id=str(project.id), topic=project.topic)

    # Kick off the Temporal workflow (non-blocking — fire and forget)
    try:
        temporal = await get_temporal_client()
        await temporal.start_workflow(
            FilmProductionWorkflow.run,
            ProductionInput(
                project_id=str(project.id),
                topic=project.topic,
                duration_minutes=project.duration_minutes,
                tone=project.tone or "documentary",
            ),
            id=f"film-{project.id}",
            task_queue="film-production",
        )
        logger.info("workflow_started", project_id=str(project.id))
    except Exception as exc:
        # Don't fail the API call if Temporal is unavailable
        logger.warning("workflow_start_failed", project_id=str(project.id), error=str(exc))

    return project


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query()] = None,
) -> ProjectListResponse:
    filters = [Project.user_id == user_id]
    if status:
        filters.append(Project.status == status)

    total = (
        await db.execute(select(func.count()).select_from(Project).where(*filters))
    ).scalar_one()

    rows = (
        await db.execute(
            select(Project)
            .where(*filters)
            .order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return ProjectListResponse(items=list(rows), total=total, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Project:
    row = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.delete("/{project_id}", response_model=ProjectResponse)
async def cancel_project(
    project_id: uuid.UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Project:
    row = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if row.status not in ("pending", "processing", "researching"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel a project with status '{row.status}'",
        )
    row.status = "cancelled"
    await db.commit()
    await db.refresh(row)

    # Also cancel the Temporal workflow if running
    try:
        temporal = await get_temporal_client()
        handle = temporal.get_workflow_handle(f"film-{project_id}")
        await handle.cancel()
    except Exception:
        pass  # workflow may not exist yet

    logger.info("project_cancelled", project_id=str(project_id))
    return row
