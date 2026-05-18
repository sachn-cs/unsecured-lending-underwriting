"""Chaos engineering tests simulating infrastructure failures.

Item 69 from production roadmap.
"""

from __future__ import annotations

import pytest

from ulu.infra.config import settings
from ulu.infra.db import DatabaseConnectionError, _create_engine_with_retry


class TestDbFailure:
    def test_engine_retry_exhaustion(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://fake")
        call_count = 0

        def fake_create_async_engine(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("simulated failure")

        monkeypatch.setattr("ulu.infra.db.create_async_engine", fake_create_async_engine)
        with pytest.raises(DatabaseConnectionError, match="simulated failure"):
            _create_engine_with_retry(retries=3)
        assert call_count == 3

    def test_engine_retry_eventual_success(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://fake")
        call_count = 0

        class FakeEngine:
            url = "postgresql+asyncpg://fake"

        def fake_create_async_engine(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("transient")
            return FakeEngine()

        monkeypatch.setattr("ulu.infra.db.create_async_engine", fake_create_async_engine)
        engine = _create_engine_with_retry(retries=3)
        assert engine is not None
        assert call_count == 2
