# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for rate limiter bounds and sweep behaviour."""

from __future__ import annotations

import time

from underwrite.rate_limit import DistributedLimiter, Limiter
from underwrite.store import Sqlite


class TestLimiterBounded:
    def test_constructor_rejects_invalid_args(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            Limiter(max_rate=0)
        with pytest.raises(ValueError):
            Limiter(max_rate=10, interval=0)
        with pytest.raises(ValueError):
            Limiter(max_rate=10, interval=1, max_buckets=0)

    def test_buckets_dict_capped_by_max_buckets(self) -> None:
        limiter = Limiter(max_rate=1_000_000, interval=1.0, max_buckets=16)
        for i in range(1_000):
            limiter.check(f"key-{i}")
        assert len(limiter.buckets) <= 16

    def test_lru_evicts_oldest_key(self) -> None:
        limiter = Limiter(max_rate=1_000_000, interval=1.0, max_buckets=4)
        for i in range(8):
            limiter.check(f"key-{i}")
        # The oldest four keys must be evicted.
        for old in range(4):
            assert f"key-{old}" not in limiter.buckets
        for recent in range(4, 8):
            assert f"key-{recent}" in limiter.buckets

    def test_evict_idle_removes_stale_entries(self) -> None:
        limiter = Limiter(max_rate=1_000_000, interval=1.0, max_buckets=64)
        limiter.check("k1")
        time.sleep(0.05)
        removed = limiter.evict_idle(idle_seconds=0.01)
        assert removed == 1
        assert "k1" not in limiter.buckets

    def test_denial_still_updates_lru(self) -> None:
        limiter = Limiter(max_rate=2, interval=10.0, max_buckets=4)
        limiter.check("k1")
        # Denials should keep the key warm in the LRU.
        assert limiter.check("k1") is False
        assert "k1" in limiter.buckets


class TestDistributedLimiterSweep:
    def test_sweep_removes_expired_store_entries(self) -> None:
        store = Sqlite(":memory:")
        limiter = DistributedLimiter(max_rate=10, interval=1.0, store=store, prefix="test")
        limiter.check("k1")
        # Rewind time so the entry is now expired.
        limiter.sweep(now=time.time() + 1_000)
        assert store.get("test:k1:0") is None

    def test_sweep_keeps_active_entries(self) -> None:
        store = Sqlite(":memory:")
        limiter = DistributedLimiter(max_rate=10, interval=1.0, store=store, prefix="test")
        limiter.check("k1")
        removed = limiter.sweep()
        assert removed == 0
        # The active entry lives under whichever window is current; just
        # assert at least one key with the prefix remains.
        keys = store.keys(pattern="test:k1:*", limit=10)
        assert keys, "expected the limiter to leave the active window entry"

    def test_sweep_without_store_is_noop(self) -> None:
        limiter = DistributedLimiter(max_rate=10, interval=1.0, store=None)
        assert limiter.sweep() == 0
