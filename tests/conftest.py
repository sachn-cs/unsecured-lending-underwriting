# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Shared fixtures for the underwrite test suite."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest

from underwrite.bus import EventBus
from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.store import InMemory, Store

# -- Domain event fixture ------------------------------------------------------


@pytest.fixture
def event() -> Message:
    """Return a minimal domain event for testing."""
    return Message(
        event_type=Type.LOAN_ORIGINATED,
        source="test",
        source_key="test",
        payload={"borrower": "alice", "principal": 10000.0, "term": 12.0},
        correlation_id="test-correlation",
    )


# -- Store fixtures ------------------------------------------------------------


@pytest.fixture
def store() -> InMemory:
    """Return a fresh InMemory instance."""
    return InMemory()


@pytest.fixture(scope="session")
def postgres_dsn() -> Generator[str, None, None]:
    """Return a Postgres DSN from env or start a testcontainer."""
    dsn = os.environ.get("UNDERWRITE_TEST_PG_DSN", "")
    if dsn:
        yield dsn
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()


@pytest.fixture
def pg_store(postgres_dsn: str) -> Generator[Store, None, None]:
    """Return a Sqlite backed by a temporary table.

    Requires the ``postgres`` extra and ``testcontainers``.
    """
    import tempfile
    from pathlib import Path

    from underwrite.store import Sqlite

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    store: Store | Sqlite = Sqlite(path=path)
    store.migrate(_empty_plan())
    yield store
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def _empty_plan() -> Any:
    from underwrite.migrate import MigrationPlan

    return MigrationPlan()


# -- Bus fixture ---------------------------------------------------------------


@pytest.fixture
def bus() -> EventBus:
    """Return a fresh EventBus instance."""
    return cast(EventBus, LocalBus())


# -- Config fixture ------------------------------------------------------------


@pytest.fixture
def tmp_config(tmp_path: Path) -> dict[str, Any]:
    """Return a dummy config file path + data for Configuration tests."""
    data = {
        "bus": {
            "rate_limit": 100.0,
            "max_workers": 4,
        },
    }
    p = tmp_path / "config.json"
    p.write_text(__import__("json").dumps(data))
    return {"path": str(p), "data": data}


# -- HTTP test client fixture --------------------------------------------------


@pytest.fixture
def client() -> Any:
    """Return a test HTTP client using the serve module.

    Requires the ``serve`` extra.
    """
    try:
        from underwrite.serve import create_app
    except ImportError:
        pytest.skip("serve extra not installed")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")
    from unittest.mock import MagicMock

    app = create_app(runtime=MagicMock())
    return TestClient(app)
