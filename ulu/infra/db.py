"""Async database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from ulu.infra.config import settings

Base = declarative_base()


def _get_engine():
    url = settings.database_url
    if not url:
        raise ValueError("DATABASE_URL is not configured")
    return create_async_engine(url, echo=settings.app_env == "development", future=True)


def _get_session_maker():
    return async_sessionmaker(bind=_get_engine(), expire_on_commit=False, autoflush=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yields an async database session for dependency injection."""
    AsyncSessionLocal = _get_session_maker()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
