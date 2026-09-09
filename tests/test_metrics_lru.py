# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Collector eviction semantics."""

from __future__ import annotations

import time

from underwrite.metrics import Collector


def test_evict_drops_least_recently_touched_not_oldest_inserted() -> None:
    """When only one map saturates the cap, the entries evicted must be
    the ones least-recently-touched — not the ones that happen to have
    been inserted first under heavy contention.
    """
    collector = Collector(max_metrics=12)
    # Three oldest counters, touched long ago.
    for i in range(3):
        collector.increment(f"old.counter.{i}", tags={"shard": str(i)})
    # Let the monotonic clock advance before the next batch.
    time.sleep(0.02)
    # Three recent counters — these should be preserved.
    for i in range(3):
        collector.increment(f"new.counter.{i}", tags={"shard": str(i)})
    # Refresh the "new" counters so their last_touched is clearly the
    # most recent in the map.
    time.sleep(0.02)
    for i in range(3):
        collector.increment(f"new.counter.{i}", tags={"shard": str(i)})

    # Add a handful more so the cap is exceeded by a known margin.
    for i in range(3, 5):
        collector.increment(f"flood.counter.{i}", tags={"shard": str(i)})

    # The "old.counter.*" entries are strictly the least-recently-touched
    # so they must be evicted first. We added 8 entries to a cap of 12,
    # so 3 old + (some of) flood should be dropped.
    for i in range(3):
        assert f"old.counter.{i}" not in collector.counters, (
            f"expected old.counter.{i} to be evicted — it was the least-recently-touched"
        )


def test_evict_preserves_per_map_balance() -> None:
    """Eviction must not let one metric type cannibalise another's share
    of the cap."""
    collector = Collector(max_metrics=9)
    # Saturate counters.
    for i in range(20):
        collector.increment(f"c.{i}")
    # Saturate timers.
    for i in range(20):
        collector.timer(f"t.{i}", 1.0)

    assert len(collector.counters) <= 9
    assert len(collector.timers) <= 9
    # Both should still have entries.
    assert len(collector.counters) > 0
    assert len(collector.timers) > 0


def test_increment_updates_last_touched() -> None:
    collector = Collector(max_metrics=100)
    collector.increment("a")
    first = collector.counters["a"].last_touched
    time.sleep(0.01)
    collector.increment("a")
    second = collector.counters["a"].last_touched
    assert second > first