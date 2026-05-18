"""
Project CRUD tests.

Unit tests mock the DB session.
Integration tests (marked) require a running postgres + migrations.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


# ── Unit tests (no real DB) ──────────────────────────────────────────────────

async def test_create_project_missing_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects",
        json={"topic": "Berlin Wall", "duration_minutes": 10},
    )
    assert response.status_code == 401


async def test_create_project_invalid_user_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects",
        json={"topic": "Berlin Wall", "duration_minutes": 10},
        headers={"X-User-ID": "not-a-uuid"},
    )
    assert response.status_code == 401


async def test_create_project_invalid_duration(
    client: AsyncClient, auth_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/projects",
        json={"topic": "Berlin Wall", "duration_minutes": 0},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_get_project_not_found(auth_headers: dict) -> None:
    from film.api.deps import get_db
    from film.main import app

    project_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            response = await c.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404


# ── Integration tests (require: make up && make migrate) ─────────────────────

@pytest.mark.integration
async def test_project_lifecycle(client: AsyncClient, auth_headers: dict) -> None:
    """Full create → get → list → cancel flow against real DB."""
    # Create
    resp = await client.post(
        "/api/v1/projects",
        json={"topic": "The Fall of Rome", "duration_minutes": 15, "tone": "dramatic"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    project = resp.json()
    assert project["status"] == "pending"
    assert project["topic"] == "The Fall of Rome"
    project_id = project["id"]

    # Get by ID
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id

    # List
    resp = await client.get("/api/v1/projects", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(p["id"] == project_id for p in body["items"])

    # Cancel
    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Double-cancel → 409
    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert resp.status_code == 409
