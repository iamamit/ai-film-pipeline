from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from film import state
from film.api.deps import get_db
from film.schemas.common import HealthResponse, ReadyResponse

logger = structlog.get_logger()
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.get("/ready", response_model=ReadyResponse)
async def readiness(db: AsyncSession = Depends(get_db)) -> ReadyResponse:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("db_readiness_failed", error=str(exc))
        checks["database"] = "error"

    try:
        if state.redis_client:
            await state.redis_client.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_initialized"
    except Exception as exc:
        logger.error("redis_readiness_failed", error=str(exc))
        checks["redis"] = "error"

    overall = "ready" if all(v == "ok" for v in checks.values()) else "degraded"
    return ReadyResponse(status=overall, checks=checks)
