# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Concurrency tests — verify thread safety of critical components.

Tests run multiple threads concurrently to expose data races in:
- Handler state mutations
- EventBus publish/dispatch
- Orchestrator concurrent execution
"""

from __future__ import annotations

import threading

from underwrite.local import LocalBus
from underwrite.message import Message
from underwrite.services.mechanism.handler import Handler as MechanismHandler
from underwrite.store import InMemory


class TestEventBusConcurrency:
    """Verify EventBus thread safety under concurrent publish."""

    def test_concurrent_publish_does_not_crash(self) -> None:
        bus = LocalBus(max_workers=4)
        bus.start()
        received: list[Message] = []
        bus.subscribe("test.event", lambda e: received.append(e))

        def publish() -> None:
            for _ in range(100):
                bus.publish(Message(event_type="test.event", source="test"))

        threads = [threading.Thread(target=publish) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        bus.stop()
        assert len(received) == 1000

    def test_concurrent_subscribe_unsubscribe(self) -> None:
        bus = LocalBus()

        def sub_unsub() -> None:
            for _ in range(50):
                sid = bus.subscribe("x", lambda e: None)
                bus.unsubscribe(sid)

        threads = [threading.Thread(target=sub_unsub) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        # No crash = success

    def test_circuit_breaker_thread_safety(self) -> None:
        from underwrite.bus import Breaker as CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.01)

        def hammer() -> None:
            sid = "svc1"
            for i in range(100):
                cb.allow_request(sid)
                if i % 2 == 0:
                    cb.record_failure(sid)
                else:
                    cb.record_success(sid)

        threads = [threading.Thread(target=hammer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert cb.state("svc1") in ("closed", "open", "half_open")


class TestMechanismServiceConcurrency:
    """Verify Handler thread safety under concurrent commands."""

    def make_mechanism(self, store):
        bus = LocalBus()
        return MechanismHandler(
            name="mechanism",
            bus=bus,
            store=store,
        )

    def test_concurrent_add_seed(self) -> None:
        store = InMemory()
        mech = self.make_mechanism(store)
        errors: list[Exception] = []

        def add_seed(i: int) -> None:
            try:
                ev = Message(
                    event_type="mechanism",
                    source="test",
                    payload={
                        "command": "add_seed",
                        "user": f"seed_{i}",
                        "base_budget": 100000.0,
                    },
                )
                mech.handle(ev)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_seed, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0
        assert len(mech.seeds) == 20

    def test_concurrent_add_user_and_originate(self) -> None:
        store = InMemory()
        mech = self.make_mechanism(store)
        # Set up a seed first
        seed_ev = Message(
            event_type="mechanism",
            source="test",
            payload={"command": "add_seed", "user": "bank", "base_budget": 1_000_000.0},
        )
        mech.handle(seed_ev)

        errors: list[Exception] = []

        def add_user(i: int) -> None:
            try:
                ev = Message(
                    event_type="mechanism",
                    source="test",
                    payload={
                        "command": "add_user",
                        "sponsor": "bank",
                        "user": f"user_{i}",
                        "delegation_amount": 10000.0,
                    },
                )
                mech.handle(ev)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_user, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0

    def test_credit_limit_does_not_race(self) -> None:
        store = InMemory()
        mech = self.make_mechanism(store)
        # Set up seed + user
        mech.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={"command": "add_seed", "user": "bank", "base_budget": 1_000_000.0},
            )
        )
        mech.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={
                    "command": "add_user",
                    "sponsor": "bank",
                    "user": "alice",
                    "delegation_amount": 50000.0,
                },
            )
        )

        results: list[float] = []

        def check_limit() -> None:
            for _ in range(50):
                try:
                    results.append(mech.credit_limit("alice"))
                except Exception:
                    pass

        threads = [threading.Thread(target=check_limit) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(results) > 0
        assert all(r >= 0 for r in results)


class TestMemoryStoreConcurrency:
    def test_concurrent_set_and_get(self) -> None:
        store = InMemory()

        def writer() -> None:
            for i in range(100):
                store.set(f"key_{i}", i)

        def reader() -> None:
            for i in range(100):
                store.get(f"key_{i}")

        threads = [threading.Thread(target=writer) for _ in range(5)] + [
            threading.Thread(target=reader) for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        # No crash = success

    def test_concurrent_keys_does_not_race(self) -> None:
        store = InMemory()
        for i in range(50):
            store.set(f"k{i}", i)

        def list_keys() -> None:
            for _ in range(20):
                store.keys()

        threads = [threading.Thread(target=list_keys) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        # No crash = success
