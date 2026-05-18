"""pytest-asyncio fixtures for async database testing."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ulu.infra.db import Base
from ulu.infra.models import (
    KycStatus,
    User,
    UserType,
)

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Provides a session-scoped event loop."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def async_engine():
    """Creates an async engine for the test session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    """Yields a fresh async session per test with automatic rollback."""
    async with async_engine.connect() as connection:
        trans = await connection.begin()
        session_maker = async_sessionmaker(bind=connection, expire_on_commit=False)
        session = session_maker()
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def seed_user(async_session):
    user = User(
        identifier="seed_1",
        user_type=UserType.SEED,
        kyc_status=KycStatus.VERIFIED,
    )
    async_session.add(user)
    await async_session.flush()
    await async_session.refresh(user)
    return user


@pytest.fixture
async def lsp_user(async_session):
    user = User(
        identifier="lsp_1",
        user_type=UserType.LSP,
        kyc_status=KycStatus.VERIFIED,
    )
    async_session.add(user)
    await async_session.flush()
    await async_session.refresh(user)
    return user


@pytest.fixture
async def borrower_user(async_session):
    user = User(
        identifier="borrower_1",
        user_type=UserType.BORROWER,
        kyc_status=KycStatus.VERIFIED,
    )
    async_session.add(user)
    await async_session.flush()
    await async_session.refresh(user)
    return user
