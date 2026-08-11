# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Shared fixtures for the underwrite test suite."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest

from underwrite.bus import EventBus
from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.store import Sqlite


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


@pytest.fixture
def store() -> Sqlite:
    """Return a fresh in-memory Sqlite instance."""
    return Sqlite(":memory:")


@pytest.fixture
def sqlite_store(tmp_path: Path) -> Generator[Sqlite, None, None]:
    """Return a file-backed Sqlite store with a temporary path."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    s = Sqlite(path=path)
    try:
        yield s
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


@pytest.fixture
def bus() -> EventBus:
    """Return a fresh EventBus instance."""
    return cast(EventBus, LocalBus())


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
