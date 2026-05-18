"""Unit of Work pattern for transaction boundary management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from ulu.infra.db import _get_session_maker


class UnitOfWork:
    """Wraps an async database session and controls commit/rollback boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


@asynccontextmanager
async def get_uow() -> AsyncGenerator[UnitOfWork, None]:
    """Yields a UnitOfWork backed by a fresh async session.

    Commits on clean exit; rolls back on exception.
    """
    AsyncSessionLocal = _get_session_maker()
    async with AsyncSessionLocal() as session:
        uow = UnitOfWork(session)
        try:
            yield uow
            await uow.commit()
        except Exception:
            await uow.rollback()
            raise
        finally:
            await session.close()
