"""Async database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from ulu.infra.config import settings

Base = declarative_base()


class DatabaseConnectionError(Exception):
    """Raised when the database is unreachable after retries."""


def _create_engine_with_retry(retries: int = 3, backoff: float = 1.0):
    url = settings.database_url
    if not url:
        raise ValueError("DATABASE_URL is not configured")
    last_exc = None
    for attempt in range(retries):
        try:
            return create_async_engine(
                url,
                echo=settings.app_env == "development",
                future=True,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600,
            )
        except (ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                import time

                time.sleep(backoff * (2 ** attempt))
    raise DatabaseConnectionError(f"database unreachable after {retries} attempts: {last_exc}") from last_exc


def _get_engine():
    return _create_engine_with_retry()


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
