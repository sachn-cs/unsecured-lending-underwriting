# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for recently added features — payload limits, store eviction, async bus timeout, etc."""

from __future__ import annotations

from typing import Any

import pytest

from underwrite.async_bus import AsyncLocalBus
from underwrite.authz import AccessControl
from underwrite.bus import Queue
from underwrite.exceptions import ProtocolError
from underwrite.message import MAX_PAYLOAD_SIZE, Message
from underwrite.store import InMemory, Store


class TestEventPayloadSizeLimit:
    """Message payload size is capped at MAX_PAYLOAD_SIZE."""

    def test_small_payload_accepted(self) -> None:
        Message(event_type="test", payload={"key": "value"})

    def test_large_payload_rejected(self) -> None:
        big = {"data": "x" * (MAX_PAYLOAD_SIZE + 1)}
        with pytest.raises(ProtocolError, match="exceeds MAX_PAYLOAD_SIZE"):
            Message(event_type="test", payload=big)

    def test_payload_at_limit_accepted(self) -> None:
        size = MAX_PAYLOAD_SIZE - 100
        Message(event_type="test", payload={"data": "x" * size})


class TestMemoryStoreEviction:
    """InMemory evicts oldest entries when max_entries is exceeded."""

    def test_unbounded_store_grows(self) -> None:
        store: Store | InMemory = InMemory(max_entries=0)
        for i in range(1000):
            store.set(f"key:{i}", i)
        assert store.get("key:0") == 0
        assert store.get("key:999") == 999

    def test_bounded_store_evicts_oldest(self) -> None:
        store: Store | InMemory = InMemory(max_entries=10)
        for i in range(20):
            store.set(f"key:{i}", i)
        assert store.get("key:0") is None
        assert store.get("key:10") == 10

    def test_bounded_store_keeps_recent(self) -> None:
        store: Store | InMemory = InMemory(max_entries=5)
        for i in range(5):
            store.set(f"key:{i}", i)
        assert store.get("key:0") == 0
        assert store.get("key:4") == 4

    def test_update_existing_key_does_not_evict(self) -> None:
        store: Store | InMemory = InMemory(max_entries=3)
        store.set("a", 1)
        store.set("b", 2)
        store.set("c", 3)
        store.set("a", 10)  # update, not new key — does not change insertion order
        store.set("d", 4)  # evicts "a" (oldest by insertion order)
        assert store.get("a") is None  # evicted (oldest insertion)
        assert store.get("b") == 2
        assert store.get("c") == 3
        assert store.get("d") == 4


class TestQueuePersistence:
    """DLQ persists and restores records via a store."""

    def test_persist_and_restore(self) -> None:
        store: Store | InMemory = InMemory()
        dlq = Queue(store=store, sync_interval=1)

        event = Message(event_type="test", payload={"msg": "hello"})
        dlq.put(event, "test error", "svc1")

        dlq2 = Queue(store=store, sync_interval=1)
        assert dlq2.count == 1
        records = dlq2.records
        assert records[0].error == "test error"
        assert records[0].event.event_type == "test"

    def test_persist_batches_by_interval(self) -> None:
        store: Store | InMemory = InMemory()
        dlq = Queue(store=store, sync_interval=5)

        for i in range(4):
            e = Message(event_type=f"test.{i}", payload={"n": i})
            dlq.put(e, f"err{i}", "svc1")

        dlq2 = Queue(store=store, sync_interval=1)
        assert dlq2.count == 0  # not synced yet

        e = Message(event_type="test.trigger", payload={"n": 5})
        dlq.put(e, "trigger", "svc1")

        dlq3 = Queue(store=store, sync_interval=1)
        assert dlq3.count == 5


class TestCryptoGuardrail:
    """AccessControl verifies signatures using cryptography."""

    def test_invalid_signature_rejected(self) -> None:
        acl = AccessControl()
        event = Message(
            event_type="test",
            source="unknown",
            signature="invalid",
        )
        result = acl.verify_signature(event)
        assert result is False


class TestAsyncBusTimeout:
    """AsyncEventBus enforces per-handler timeout."""

    @pytest.mark.asyncio
    async def test_handler_timeout_sends_to_dlq(self) -> None:
        bus = AsyncLocalBus(maxsize=100, handler_timeout=0.1)

        async def slow_handler(event: Any) -> None:
            import asyncio

            await asyncio.sleep(5.0)

        await bus.subscribe("test.timeout", slow_handler)
        await bus.start()

        event = Message(event_type="test.timeout")
        await bus.publish(event)
        import asyncio

        await asyncio.sleep(0.5)

        assert bus.dlq.count >= 1, f"expected timed-out event in DLQ, got {bus.dlq.count}"
        dlq_records = bus.dlq.records
        assert any("timed out" in rec.error for rec in dlq_records), (
            f"DLQ record should carry the timeout error, got {[r.error for r in dlq_records]}"
        )

        await bus.stop()

    @pytest.mark.asyncio
    async def test_fast_handler_succeeds(self) -> None:
        bus = AsyncLocalBus(maxsize=100)
        results: list[str] = []

        async def fast_handler(event: Any) -> None:
            results.append(event.event_type)

        await bus.subscribe("test.fast", fast_handler)
        await bus.start()

        event = Message(event_type="test.fast")
        await bus.publish(event)
        import asyncio

        await asyncio.sleep(0.2)

        assert "test.fast" in results
        await bus.stop()

    @pytest.mark.asyncio
    async def test_bus_cancel_on_stop(self) -> None:
        bus = AsyncLocalBus(maxsize=100)
        await bus.start()
        await bus.stop()
        assert bus.dlq is not None


class TestCircuitBreakerHalfOpenTransition:
    """CircuitBreaker transitions to half-open after cooldown."""

    def test_half_open_after_cooldown(self) -> None:
        from underwrite.circuit import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05, name="test")

        assert cb.state == CircuitState.CLOSED

        def _raise_value_error() -> Any:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            cb.call(_raise_value_error)
        with pytest.raises(ValueError):
            cb.call(_raise_value_error)

        import time

        deadline = time.monotonic() + 5.0
        while cb.state == CircuitState.OPEN:
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN

    def test_recovery_after_half_open_success(self) -> None:
        from underwrite.circuit import CircuitBreaker, CircuitState

        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05, name="test")

        def _raise_value_error() -> Any:
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_raise_value_error)

        import time

        deadline = time.monotonic() + 5.0
        while cb.state == CircuitState.OPEN:
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN

        cb.call(lambda: "success")
        assert cb.state == CircuitState.CLOSED


class TestDistributedLimiter:
    """DistributedLimiter falls back to in-memory when no store."""

    def test_in_memory_fallback(self) -> None:
        from underwrite.bus import DistributedLimiter

        rl = DistributedLimiter(max_rate=1000.0, interval=1.0, store=None)
        assert rl.check("test") is True

    def test_distributed_with_store(self) -> None:
        from underwrite.bus import DistributedLimiter

        store: Store | InMemory = InMemory()
        rl = DistributedLimiter(max_rate=100.0, interval=10.0, store=store, prefix="testrl")
        assert rl.check("key1") is True
        import time

        time.sleep(0.15)
        assert rl.check("key1") is True


class TestGuard:
    """Guard correctly detects duplicates."""

    def test_first_call_not_duplicate(self) -> None:
        from underwrite.bus import Guard

        guard = Guard()
        assert guard.is_duplicate("h1", "e1") is False

    def test_second_call_is_duplicate(self) -> None:
        from underwrite.bus import Guard

        guard = Guard()
        guard.is_duplicate("h1", "e1")
        assert guard.is_duplicate("h1", "e1") is True

    def test_different_handlers_independent(self) -> None:
        from underwrite.bus import Guard

        guard = Guard()
        guard.is_duplicate("h1", "e1")
        assert guard.is_duplicate("h2", "e1") is False


class TestEventSlots:
    """Message dataclass uses __slots__ for memory efficiency."""

    def test_slots_defined(self) -> None:
        e = Message(event_type="test")
        assert not hasattr(e, "__dict__")

    def test_slots_contains_fields(self) -> None:
        assert hasattr(Message, "__slots__")
        slots = Message.__slots__
        assert "event_id" in slots
        assert "payload" in slots
        assert "trace_id" in slots
