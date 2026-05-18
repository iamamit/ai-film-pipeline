"""Unit tests for health endpoints — no real DB or Redis required."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


async def test_readiness_db_ok(client: AsyncClient) -> None:
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    with patch("film.api.health.get_db", return_value=mock_session):
        response = await client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["redis"] == "ok"


async def test_readiness_redis_down(client: AsyncClient) -> None:
    from film import state

    state.redis_client.ping = AsyncMock(side_effect=ConnectionError("refused"))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    with patch("film.api.health.get_db", return_value=mock_session):
        response = await client.get("/ready")

    body = response.json()
    assert body["checks"]["redis"] == "error"
    assert body["status"] == "degraded"
