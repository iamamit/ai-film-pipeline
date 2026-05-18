"""
Test fixtures.

Unit tests run without docker (DB and Redis are mocked).
Integration tests (marked @pytest.mark.integration) require the full
docker-compose stack: make up && make migrate
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from film import state
from film.main import app


@pytest.fixture
def user_id() -> str:
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def auth_headers(user_id: str) -> dict[str, str]:
    return {"X-User-ID": user_id}


@pytest.fixture(autouse=True)
def mock_redis():
    """Inject a mock Redis client so unit tests don't need a real Redis."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    state.redis_client = mock
    yield mock
    state.redis_client = None


@pytest.fixture
async def client(mock_redis) -> AsyncClient:
    """Async HTTP test client backed by the FastAPI ASGI app.

    The lifespan is NOT run — dependencies are mocked directly via fixtures.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
