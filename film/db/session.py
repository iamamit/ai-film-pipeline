from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from film.core.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        yield session
