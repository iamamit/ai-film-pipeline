import structlog
from temporalio.client import Client

from film.core.config import get_settings

logger = structlog.get_logger()

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
        logger.info("temporal_connected", host=settings.temporal_host)
    return _client


def set_temporal_client(client: Client) -> None:
    """Used in tests to inject a mock client."""
    global _client
    _client = client
