import json

import structlog
from aiokafka import AIOKafkaProducer

from film.core.config import get_settings

logger = structlog.get_logger()


class FilmProducer:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        settings = get_settings()
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
            key_serializer=lambda k: k.encode() if k else None,
        )
        await self._producer.start()
        logger.info("kafka_producer_started", servers=settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("kafka_producer_stopped")

    async def publish(self, topic: str, payload: dict, key: str | None = None) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started — call start() first")
        await self._producer.send_and_wait(topic, value=payload, key=key)
        logger.debug("event_published", topic=topic, event_type=payload.get("type", "unknown"))
