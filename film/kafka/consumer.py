import json
from abc import ABC, abstractmethod

import structlog
from aiokafka import AIOKafkaConsumer, ConsumerRecord

from film.core.config import get_settings

logger = structlog.get_logger()


class FilmConsumer(ABC):
    """Base class for all Kafka consumers. Subclass and implement handle()."""

    def __init__(self, topic_list: list[str], group_id: str) -> None:
        self._topics = topic_list
        self._group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        settings = get_settings()
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode()),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        logger.info("kafka_consumer_started", topics=self._topics, group=self._group_id)

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()
            logger.info("kafka_consumer_stopped", group=self._group_id)

    async def run(self) -> None:
        if not self._consumer:
            raise RuntimeError("Consumer not started — call start() first")
        async for msg in self._consumer:
            await self._process(msg)

    async def _process(self, msg: ConsumerRecord) -> None:
        try:
            await self.handle(msg)
        except Exception as exc:
            logger.error(
                "message_handling_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=str(exc),
            )
            # TODO Phase 2: re-publish to DLQ via shared producer

    @abstractmethod
    async def handle(self, msg: ConsumerRecord) -> None:
        """Process a single Kafka message. Override in subclasses."""
