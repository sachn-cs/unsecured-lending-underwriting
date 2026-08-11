# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Integration tests — end-to-end bus → service → store → bus pipeline.

Tests verify that real services react correctly when wired through the
Runtime and events flow through the full pipeline.
"""

from __future__ import annotations

from typing import Any, cast

from underwrite.config import Configuration
from underwrite.message import Message, Type
from underwrite.runtime import Runtime
from underwrite.store import Sqlite


def memory_runtime() -> Runtime:
    """Returns a Runtime backed by Sqlite for test isolation."""
    cfg = Configuration.default()
    cfg.store.backend = "memory"
    cfg.metrics.enabled = False
    cfg.authz.enabled = False
    return Runtime(config=cfg)


class TestRuntimeIntegration:
    """End-to-end tests using the full Runtime."""

    def test_start_stop_services(self) -> None:
        cfg = Configuration.default()
        cfg.authz.enabled = False
        rt = Runtime(config=cfg)
        rt.register("mechanism")
        rt.wire("mechanism")
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        assert svc is not None
        assert svc.is_running
        rt.stop()
        svc = rt.get("mechanism")
        assert svc is not None
        assert svc.is_running is False

    def test_mechanism_emits_seed_added(self) -> None:
        rt = memory_runtime()
        bus = rt.bus
        received: list[Message] = []
        bus.subscribe("*", lambda e: received.append(e))
        rt.register("mechanism")
        rt.wire("mechanism")
        bus.start()
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        assert svc is not None
        svc.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={"command": "add_seed", "user": "bank", "base_budget": 100000},
            )
        )
        assert any(e.event_type == Type.SEED_ADDED for e in received)

    def test_store_persists_across_start_stop(self) -> None:
        cfg = Configuration.default()
        cfg.authz.enabled = False
        rt = Runtime(config=cfg)
        rt.register("mechanism")
        rt.wire("mechanism")
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        assert svc is not None
        svc.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={"command": "add_seed", "user": "bank", "base_budget": 100000},
            )
        )
        orig_state = rt.store.get("protocol:state")
        rt.stop()
        assert orig_state is not None
        assert "bank" in orig_state["seeds"]

    def test_bus_delivers_to_subscribed_service(self) -> None:
        cfg = Configuration.default()
        cfg.authz.enabled = False
        rt = Runtime(config=cfg)
        bus = rt.bus
        rt.register("audit")
        rt.wire("audit")
        bus.start()
        rt.start(["audit"])
        bus.publish(
            Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={"borrower": "alice", "principal": 10000})
        )
        audit = cast(Any, rt.get("audit"))
        assert audit is not None
        assert len(audit.ledger) >= 1
        assert audit.ledger[0]["event_type"] == Type.LOAN_ORIGINATED

    def test_mechanism_rejects_with_bus(self) -> None:
        cfg = Configuration.default()
        cfg.authz.enabled = False
        rt = Runtime(config=cfg)
        bus = rt.bus
        received: list[Message] = []
        bus.subscribe("mechanism.rejected", lambda e: received.append(e))
        rt.register("mechanism")
        rt.wire("mechanism")
        bus.start()
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        assert svc is not None
        svc.handle(
            Message(
                event_type="mechanism", source="test", payload={"command": "add_seed", "user": "bank", "base_budget": 0}
            )
        )
        assert len(received) == 1
        assert received[0].payload["reason"] is not None

    def test_full_loan_lifecycle(self) -> None:
        rt = memory_runtime()
        bus = rt.bus
        all_events: list[Message] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        rt.register("mechanism")
        rt.register("audit")
        rt.wire("mechanism")
        rt.wire("audit")
        bus.start()
        rt.start(["mechanism", "audit"])
        svc = rt.get("mechanism")
        assert svc is not None

        svc.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={"command": "add_seed", "user": "bank", "base_budget": 1_000_000},
            )
        )
        svc.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={"command": "add_user", "sponsor": "bank", "user": "alice", "delegation_amount": 500_000},
            )
        )
        svc.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={
                    "command": "originate",
                    "borrower": "alice",
                    "principal": 100000,
                    "term": 12,
                    "default_probability": 0.02,
                    "protocol_rate": 0.10,
                    "max_delegation_rate": 0.05,
                },
            )
        )

        emitted = {e.event_type for e in all_events}
        assert Type.SEED_ADDED in emitted
        assert Type.USER_ADDED in emitted
        assert Type.LOAN_ORIGINATED in emitted

        audit = cast(Any, rt.get("audit"))
        assert audit is not None
        assert len(audit.ledger) >= 3
        rt.stop()


class TestStoreIntegration:
    def test_memory_store_round_trip(self) -> None:
        store = Sqlite(":memory:")
        store.set("key", {"nested": [1, 2, 3]})
        assert store.get("key") == {"nested": [1, 2, 3]}
        assert store.exists("key")
        assert store.delete("key")
        assert store.get("key") is None

    def test_keys_pattern(self) -> None:
        store = Sqlite(":memory:")
        store.set("a:1", 1)
        store.set("a:2", 2)
        store.set("b:1", 3)
        assert len(store.keys("a:")) == 2


class TestCrossServiceCommunication:
    def test_two_services_share_store(self) -> None:
        rt = memory_runtime()
        bus = rt.bus
        bus.start()
        rt.register("mechanism")
        rt.register("audit")
        rt.wire("mechanism")
        rt.wire("audit")
        rt.start(["mechanism", "audit"])
        svc = rt.get("mechanism")
        assert svc is not None
        svc.handle(
            Message(
                event_type="mechanism",
                source="test",
                payload={"command": "add_seed", "user": "bank", "base_budget": 100000},
            )
        )
        state = rt.store.get("protocol:state")
        assert state is not None
        assert "bank" in state["seeds"]
        rt.stop()
