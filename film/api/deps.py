import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from film.db.session import get_db_session

# Exposes the Authorize button in Swagger UI for X-User-ID
_user_id_scheme = APIKeyHeader(name="X-User-ID", scheme_name="X-User-ID", auto_error=False)


async def get_current_user(
    x_user_id: Annotated[str | None, Security(_user_id_scheme)] = None,
) -> uuid.UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    try:
        return uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid X-User-ID header — must be a UUID")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


CurrentUser = Annotated[uuid.UUID, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
