"""Module-level singletons set during FastAPI lifespan and shared across requests."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from film.kafka.producer import FilmProducer

redis_client: "Redis | None" = None
kafka_producer: "FilmProducer | None" = None
