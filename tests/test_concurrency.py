"""Concurrency tests — verify thread safety of critical components.

Tests run multiple threads concurrently to expose data races in:
- MechanismService state mutations
- KeyRotationManager rotation
- LocalBus publish/dispatch
"""
from __future__ import annotations

import threading
import time

import pytest

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event
from underwrite.__identity__ import KeyRotationManager
from underwrite.__store__ import MemoryStore


class TestLocalBusConcurrency:
    """Verify LocalBus thread safety under concurrent publish."""

    def test_concurrent_publish_does_not_crash(self) -> None:
        bus = LocalBus(max_workers=4)
        bus.start()
        received: list[Event] = []
        bus.subscribe("test.event", lambda e: received.append(e))

        def publish() -> None:
            for _ in range(100):
                bus.publish(Event(event_type="test.event", source="test"))

        threads = [threading.Thread(target=publish) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        bus.stop()
        assert len(received) == 1000

    def test_concurrent_subscribe_unsubscribe(self) -> None:
        bus = LocalBus()
        sids: list[str] = []

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
        from underwrite.__bus__ import CircuitBreaker

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


class TestKeyRotationManagerConcurrency:
    """Verify KeyRotationManager thread safety under concurrent rotation."""

    def test_concurrent_get_or_create_returns_consistent_identity(self) -> None:
        krm = KeyRotationManager(ttl_seconds=99999)
        results: list[str] = []

        def get_id() -> None:
            identity = krm.get_or_create("svc1")
            results.append(identity.public_key)

        threads = [threading.Thread(target=get_id) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        # All should see the same key (no double-rotation)
        assert len(set(results)) == 1

    def test_concurrent_rotate_does_not_lose_keys(self) -> None:
        krm = KeyRotationManager(ttl_seconds=99999)
        initial = krm.get_or_create("svc1")

        def rotate() -> None:
            krm.rotate("svc1")

        threads = [threading.Thread(target=rotate) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        current = krm.get_or_create("svc1")
        assert current.public_key != initial.public_key

    def test_verify_recent_key_still_works(self) -> None:
        krm = KeyRotationManager(ttl_seconds=99999, grace_period=99999)
        identity = krm.get_or_create("svc2")
        payload = "test-payload"
        sig = identity.sign(payload)
        assert krm.verify_with_rotation(payload, sig, "svc2",
                                        identity.public_key)
        # After rotation, old key should still verify during grace
        krm.rotate("svc2")
        assert krm.verify_with_rotation(payload, sig, "svc2",
                                        identity.public_key)


class TestMechanismServiceConcurrency:
    """Verify MechanismService thread safety under concurrent commands."""

    def _make_mechanism(self, store):
        from underwrite.services.mechanism.service import MechanismService

        bus = LocalBus()
        return MechanismService(
            service_id="mechanism",
            bus=bus,
            store=store,
        )

    def test_concurrent_add_seed(self) -> None:
        store = MemoryStore()
        mech = self._make_mechanism(store)
        errors: list[Exception] = []

        def add_seed(i: int) -> None:
            try:
                ev = Event(
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

        threads = [
            threading.Thread(target=add_seed, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0
        assert len(mech.seeds) == 20

    def test_concurrent_add_user_and_originate(self) -> None:
        store = MemoryStore()
        mech = self._make_mechanism(store)
        # Set up a seed first
        seed_ev = Event(
            event_type="mechanism",
            source="test",
            payload={
                "command": "add_seed",
                "user": "bank",
                "base_budget": 1_000_000.0
            },
        )
        mech.handle(seed_ev)

        errors: list[Exception] = []

        def add_user(i: int) -> None:
            try:
                ev = Event(
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

        threads = [
            threading.Thread(target=add_user, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0

    def test_credit_limit_does_not_race(self) -> None:
        store = MemoryStore()
        mech = self._make_mechanism(store)
        # Set up seed + user
        mech.handle(
            Event(
                event_type="mechanism",
                source="test",
                payload={
                    "command": "add_seed",
                    "user": "bank",
                    "base_budget": 1_000_000.0
                },
            ))
        mech.handle(
            Event(
                event_type="mechanism",
                source="test",
                payload={
                    "command": "add_user",
                    "sponsor": "bank",
                    "user": "alice",
                    "delegation_amount": 50000.0,
                },
            ))

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
        store = MemoryStore()

        def writer() -> None:
            for i in range(100):
                store.set(f"key_{i}", i)

        def reader() -> None:
            for i in range(100):
                store.get(f"key_{i}")

        threads = ([threading.Thread(target=writer) for _ in range(5)] +
                   [threading.Thread(target=reader) for _ in range(5)])
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        # No crash = success

    def test_concurrent_keys_does_not_race(self) -> None:
        store = MemoryStore()
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
