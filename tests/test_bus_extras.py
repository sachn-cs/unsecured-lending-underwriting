# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Queue and Limiter."""

from __future__ import annotations

import time

import pytest

from underwrite.async_bus import AsyncLocalBus
from underwrite.bus import DistributedLimiter, Guard, Limiter
from underwrite.dlq import Queue
from underwrite.exceptions import RateLimitError
from underwrite.local import LocalBus
from underwrite.message import Message
from underwrite.store import Sqlite


class TestQueue:
    def test_empty_by_default(self) -> None:
        dlq = Queue()
        assert dlq.count == 0
        assert list(dlq.records.values()) == []

    def test_put_and_count(self) -> None:
        dlq = Queue()
        dlq.put(Message(event_type="t", source="s"), "error", "sub1")
        assert dlq.count == 1

    def test_clear(self) -> None:
        dlq = Queue()
        dlq.put(Message(event_type="t", source="s"), "err", "s1")
        dlq.clear()
        assert dlq.count == 0

    def test_replay(self) -> None:
        bus = LocalBus()
        dlq = Queue()
        dlq.put(Message(event_type="t", source="s", payload={"k": "v"}), "err", "s1")
        bus.start()
        n = dlq.replay(bus)
        assert n == 1

    def test_replay_with_max(self) -> None:
        bus = LocalBus()
        dlq = Queue()
        dlq.put(Message(event_type="t1", source="s"), "err", "s1")
        dlq.put(Message(event_type="t2", source="s"), "err", "s1")
        n = dlq.replay(bus, max_count=1)
        assert n == 1
        assert dlq.count == 1

    def test_put_redacts_pii(self) -> None:
        dlq = Queue()
        dlq.put(
            Message(
                event_type="loan.originated", source="origination", payload={"pan": "ABCDE1234F", "loan_id": "L100"}
            ),
            "err",
            "s1",
        )
        record = next(iter(dlq.records.values()))
        assert record.event.payload["pan"] == "***REDACTED***"
        assert record.event.payload["loan_id"] == "L100"

    def test_cap_evicts_oldest(self) -> None:
        dlq = Queue(max_records=3)
        for i in range(5):
            dlq.put(Message(event_type=f"e{i}", source="s"), "err", "s1")
        assert dlq.count == 3
        # oldest two evicted; youngest three remain
        remaining = [r.event.event_type for r in dlq.records.values()]
        assert remaining == ["e2", "e3", "e4"]


class TestAsyncEventBusShutdown:
    def test_stop_event_wakes_dispatch_loop(self) -> None:
        """Stopping the bus must wake the dispatch loop immediately,
        not after a 1-second timeout-based wakeup."""
        import asyncio

        async def run() -> None:
            bus = AsyncLocalBus()
            await bus.start()
            await asyncio.sleep(0.05)
            await bus.stop()
            assert bus.is_stopped() is True

        asyncio.run(run())


class TestDistributedLimiterTTL:
    def test_expired_window_is_recycled(self) -> None:
        """A window whose end has passed must allow the next event
        even on stores that lack a native TTL."""
        from underwrite.store import Sqlite

        store = Sqlite(":memory:")
        limiter = DistributedLimiter(max_rate=1.0, interval=1.0, store=store)
        # Manually inject an "expired" window entry
        store.set("ratelimit:alice:0", {"expires_at": 0.0})
        assert limiter.check("alice") is True

    def test_active_window_blocks(self) -> None:
        from underwrite.store import Sqlite

        store = Sqlite(":memory:")
        limiter = DistributedLimiter(max_rate=1.0, interval=10.0, store=store)
        assert limiter.check("alice") is True
        assert limiter.check("alice") is False


class TestGuardBoundedHandlers:
    def test_evicts_oldest_handler_when_global_cap_reached(self) -> None:
        from underwrite.bus import Guard

        guard = Guard(max_ids_per_handler=10, max_handlers=2)
        assert guard.is_duplicate("h1", "e1") is False
        assert guard.is_duplicate("h2", "e1") is False
        # Adding a third handler should evict h1
        assert guard.is_duplicate("h3", "e1") is False
        # h1's entries were evicted; h1 should be a fresh bucket now
        assert guard.is_duplicate("h1", "e1") is False


class TestLimiter:
    def test_allows_first_call(self) -> None:
        rl = Limiter(max_rate=10)
        assert rl.check("key") is True

    def test_blocks_excessive_calls(self) -> None:
        rl = Limiter(max_rate=1000)
        rl.check("key")
        allowed = [rl.check("key") for _ in range(10)]
        assert not all(allowed)

    def test_assert_allowed_passes(self) -> None:
        rl = Limiter(max_rate=10)
        rl.assert_allowed("key")

    def test_assert_allowed_raises(self) -> None:
        rl = Limiter(max_rate=1000)
        rl.check("key")
        with pytest.raises(RateLimitError):
            rl.assert_allowed("key")

    def test_recovery_after_interval(self) -> None:
        rl = Limiter(max_rate=1000000, interval=0.001)
        rl.assert_allowed("k")
        time.sleep(0.002)
        rl.assert_allowed("k")


class TestEventBusDLQ:
    def test_failed_handler_goes_to_dlq(self) -> None:
        bus = LocalBus()
        bus.subscribe("test.fail", lambda e: (_ for _ in ()).throw(RuntimeError("fail")))
        bus.start()
        bus.publish(Message(event_type="test.fail", source="s"))
        assert bus.dlq.count == 1

    def test_healthy_handler_skips_dlq(self) -> None:
        bus = LocalBus()
        results: list = []
        bus.subscribe("test.ok", lambda e: results.append(1))
        bus.start()
        bus.publish(Message(event_type="test.ok", source="s"))
        assert bus.dlq.count == 0
        assert results == [1]


class TestQueuePersistence:
    def test_put_persists_to_store(self) -> None:
        store = Sqlite(":memory:")
        dlq = Queue(store=store, sync_interval=1)
        dlq.put(Message(event_type="t", source="s", payload={"k": "v"}), "err", "sub1")
        raw = store.get("bus:dlq")
        assert raw is not None
        assert isinstance(raw, list)
        assert len(raw) == 1
        assert raw[0]["error"] == "err"
        assert raw[0]["subscriber_id"] == "sub1"
        assert raw[0]["event"]["event_type"] == "t"

    def test_loads_from_store_on_init(self) -> None:
        store = Sqlite(":memory:")
        dlq1 = Queue(store=store, sync_interval=1)
        dlq1.put(Message(event_type="t1", source="s"), "err1", "sub1")
        dlq1.put(Message(event_type="t2", source="s"), "err2", "sub2")

        dlq2 = Queue(store=store, sync_interval=1)
        assert dlq2.count == 2
        types = [r.event.event_type for r in dlq2.records.values()]
        assert "t1" in types
        assert "t2" in types

    def test_clear_removes_from_store(self) -> None:
        store = Sqlite(":memory:")
        dlq = Queue(store=store, sync_interval=1)
        dlq.put(Message(event_type="t", source="s"), "err", "sub1")
        dlq.clear()
        raw = store.get("bus:dlq")
        assert raw == []

    def test_replay_removes_from_store(self) -> None:
        store = Sqlite(":memory:")
        bus = LocalBus()
        dlq = Queue(store=store, sync_interval=1)
        dlq.put(Message(event_type="t", source="s"), "err", "sub1")
        dlq.replay(bus)
        raw = store.get("bus:dlq")
        assert raw == []


class TestDistributedLimiter:
    def test_falls_back_to_in_memory_without_store(self) -> None:
        rl = DistributedLimiter(max_rate=1000)
        assert rl.check("key") is True

    def test_store_backed_allows_first_call(self) -> None:
        store = Sqlite(":memory:")
        rl = DistributedLimiter(max_rate=10, store=store)
        assert rl.check("key") is True

    def test_store_backed_blocks_excessive_calls(self) -> None:
        store = Sqlite(":memory:")
        rl = DistributedLimiter(max_rate=1000, store=store)
        rl.check("key")
        allowed = [rl.check("key") for _ in range(10)]
        assert not all(allowed)

    def test_store_backed_shares_state(self) -> None:
        store = Sqlite(":memory:")
        rl1 = DistributedLimiter(max_rate=1000, store=store, prefix="shared")
        rl2 = DistributedLimiter(max_rate=1000, store=store, prefix="shared")
        rl1.check("k")
        # rl2 sees the same rate-limit state from the store
        allowed = [rl2.check("k") for _ in range(10)]
        assert not all(allowed)

    def test_respects_custom_prefix(self) -> None:
        store = Sqlite(":memory:")
        rl1 = DistributedLimiter(max_rate=1000, store=store, prefix="p1")
        rl2 = DistributedLimiter(max_rate=1000, store=store, prefix="p2")
        rl1.check("k")
        # Different prefix = independent bucket
        assert rl2.check("k") is True


class TestGuard:
    def test_new_event_not_duplicate(self) -> None:
        guard = Guard()
        assert guard.is_duplicate("h1", "e1") is False

    def test_repeat_event_is_duplicate(self) -> None:
        guard = Guard()
        guard.is_duplicate("h1", "e1")
        assert guard.is_duplicate("h1", "e1") is True

    def test_tracked_separately_per_handler(self) -> None:
        guard = Guard()
        guard.is_duplicate("h1", "e1")
        assert guard.is_duplicate("h2", "e1") is False

    def test_total_tracked_events(self) -> None:
        guard = Guard()
        guard.is_duplicate("h1", "a")
        guard.is_duplicate("h1", "b")
        guard.is_duplicate("h2", "a")
        assert guard.total_tracked_events == 3

    def test_total_tracked_events_eviction(self) -> None:
        guard = Guard(max_ids_per_handler=3)
        guard.is_duplicate("h1", "e1")
        guard.is_duplicate("h1", "e2")
        guard.is_duplicate("h1", "e3")
        assert guard.total_tracked_events == 3
        guard.is_duplicate("h1", "e4")  # evicts e1
        assert guard.total_tracked_events == 3
        # e1 is no longer duplicate
        assert guard.is_duplicate("h1", "e1") is False
