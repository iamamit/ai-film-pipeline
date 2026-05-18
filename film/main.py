from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from film import state
from film.api.health import router as health_router
from film.api.v1.router import api_v1_router
from film.core.config import get_settings
from film.core.logging import setup_logging
from film.db.session import engine
from film.kafka.producer import FilmProducer

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level, settings.environment)
    logger.info("startup_begin", environment=settings.environment)

    # Required: database
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database_ready")

    # Required: Redis
    state.redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await state.redis_client.ping()
    logger.info("redis_ready")

    # Optional: Temporal (warn on failure — not needed until Phase 2)
    try:
        from film.temporal.client import get_temporal_client
        await get_temporal_client()
        logger.info("temporal_ready")
    except Exception as exc:
        logger.warning("temporal_unavailable", error=str(exc))

    # Optional: Kafka producer (warn on failure — not needed until Phase 2)
    try:
        state.kafka_producer = FilmProducer()
        await state.kafka_producer.start()
        logger.info("kafka_producer_ready")
    except Exception as exc:
        logger.warning("kafka_unavailable", error=str(exc))
        state.kafka_producer = None

    logger.info("startup_complete")
    yield

    # Shutdown — reverse order
    if state.kafka_producer:
        await state.kafka_producer.stop()
    if state.redis_client:
        await state.redis_client.aclose()
    await engine.dispose()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Film Production Pipeline",
        version="0.1.0",
        description="Distributed AI orchestration for documentary-style video generation",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(api_v1_router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", path=str(request.url), error=str(exc), exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()
