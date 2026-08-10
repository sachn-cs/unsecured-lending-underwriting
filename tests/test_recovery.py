# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — multi-stage post-default recovery orchestration.

Tests verify the full recovery workflow with store-backed persistence:
  DEFAULT_OCCURRED -> RECOVERY_STARTED -> recovery.offer ->
  recovery.offer_response (accepted) -> PAYMENT_PLAN ->
  PAYMENT_RECEIVED -> RECOVERY_COMPLETED
"""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.recovery.handler import Handler
from underwrite.services.recovery.handler import Handler as RecoveryHandler
from underwrite.store import InMemory


def _recovery(bus=None) -> Handler:
    svc = RecoveryHandler(name="recovery", bus=bus, store=InMemory())
    svc.repo.save({})
    return svc


class TestRecoveryService:
    def test_emits_started_on_default(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RECOVERY_STARTED, lambda e: received.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "alice", "principal": 50000})
        )
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert received[0].payload["principal"] == 50000.0
        assert received[0].payload["stage"] == "negotiation"
        assert "started_at" in received[0].payload

    def test_default_triggers_offer(self) -> None:
        bus = LocalBus()
        started: list[Message] = []
        offers: list[Message] = []
        bus.subscribe(Type.RECOVERY_STARTED, lambda e: started.append(e))
        bus.subscribe("recovery.offer", lambda e: offers.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "bob", "principal": 100000})
        )
        assert len(started) == 1
        assert len(offers) == 1
        assert offers[0].payload["borrower"] == "bob"
        assert offers[0].payload["offer_amount"] == 30000.0

    def test_does_not_emit_completed_on_default(self) -> None:
        bus = LocalBus()
        completed: list[Message] = []
        bus.subscribe(Type.RECOVERY_COMPLETED, lambda e: completed.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "carol", "principal": 50000})
        )
        assert len(completed) == 0

    def test_emits_completed_after_full_recovery(self) -> None:
        bus = LocalBus()
        completed: list[Message] = []
        bus.subscribe(Type.RECOVERY_COMPLETED, lambda e: completed.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "dave", "principal": 10000})
        )
        svc.handle(
            Message(event_type=Type.PAYMENT_RECEIVED, source="test", payload={"borrower": "dave", "amount": 10000})
        )
        assert len(completed) == 1
        assert completed[0].payload["recovered"] == 10000.0
        assert completed[0].payload["outstanding"] == 0.0

    def test_offer_rejection_retriggers_offer(self) -> None:
        bus = LocalBus()
        offers: list[Message] = []
        bus.subscribe("recovery.offer", lambda e: offers.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "eve", "principal": 30000})
        )
        offers.clear()
        svc.handle(
            Message(event_type="recovery.offer_response", source="test", payload={"borrower": "eve", "accepted": False})
        )
        assert len(offers) == 1
        assert offers[0].payload["offer_amount"] == 9000.0

    def test_three_rejections_escalates(self) -> None:
        bus = LocalBus()
        escalated: list[Message] = []
        bus.subscribe("recovery.escalated", lambda e: escalated.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "faythe", "principal": 10000})
        )
        for _ in range(3):
            svc.handle(
                Message(
                    event_type="recovery.offer_response",
                    source="test",
                    payload={"borrower": "faythe", "accepted": False},
                )
            )
        assert len(escalated) == 1
        assert escalated[0].payload["borrower"] == "faythe"
        assert escalated[0].payload["stage"] == "escalation"

    def test_offer_accepted_enters_payment_plan(self) -> None:
        bus = LocalBus()
        started: list[Message] = []
        bus.subscribe(Type.RECOVERY_STARTED, lambda e: started.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "grace", "principal": 20000})
        )
        started.clear()
        svc.handle(
            Message(
                event_type="recovery.offer_response", source="test", payload={"borrower": "grace", "accepted": True}
            )
        )
        assert len(started) == 1
        assert started[0].payload["stage"] == "payment_plan"

    def test_partial_payment_emits_progress(self) -> None:
        bus = LocalBus()
        progress: list[Message] = []
        bus.subscribe("recovery.progress", lambda e: progress.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "heidi", "principal": 5000})
        )
        svc.handle(
            Message(event_type=Type.PAYMENT_RECEIVED, source="test", payload={"borrower": "heidi", "amount": 2000})
        )
        assert len(progress) == 1
        assert progress[0].payload["recovered"] == 2000.0
        assert progress[0].payload["outstanding"] == 3000.0

    def test_partial_then_full_payment_completes(self) -> None:
        bus = LocalBus()
        completed: list[Message] = []
        bus.subscribe(Type.RECOVERY_COMPLETED, lambda e: completed.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "ivan", "principal": 8000})
        )
        svc.handle(
            Message(event_type=Type.PAYMENT_RECEIVED, source="test", payload={"borrower": "ivan", "amount": 5000})
        )
        svc.handle(
            Message(event_type=Type.PAYMENT_RECEIVED, source="test", payload={"borrower": "ivan", "amount": 3000})
        )
        assert len(completed) == 1
        assert completed[0].payload["recovered"] == 8000.0

    def test_unknown_borrower_payment_silently_ignored(self) -> None:
        bus = LocalBus()
        progress: list[Message] = []
        bus.subscribe("recovery.progress", lambda e: progress.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.PAYMENT_RECEIVED, source="test", payload={"borrower": "nobody", "amount": 1000})
        )
        assert len(progress) == 0

    def test_unknown_borrower_offer_response_silently_ignored(self) -> None:
        bus = LocalBus()
        started: list[Message] = []
        bus.subscribe(Type.RECOVERY_STARTED, lambda e: started.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type="recovery.offer_response", source="test", payload={"borrower": "nobody", "accepted": True}
            )
        )
        assert len(started) == 0

    def test_ignores_non_default_events(self) -> None:
        bus = LocalBus()
        started: list[Message] = []
        bus.subscribe(Type.RECOVERY_STARTED, lambda e: started.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        svc.handle(Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={}))
        assert len(started) == 0

    def test_recovery_state_persisted(self) -> None:
        bus = LocalBus()
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.DEFAULT_OCCURRED,
                source="test",
                payload={"borrower": "persist_test", "principal": 50000},
            )
        )
        recovery = svc.get_recovery("persist_test")
        assert recovery is not None
        assert recovery["borrower"] == "persist_test"
        assert recovery["principal"] == 50000.0
        assert recovery["stage"] == "negotiation"

    def test_duplicate_default_skipped(self) -> None:
        bus = LocalBus()
        started: list[Message] = []
        bus.subscribe(Type.RECOVERY_STARTED, lambda e: started.append(e))
        svc = _recovery(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.DEFAULT_OCCURRED,
                source="test",
                payload={"borrower": "dup_test", "principal": 50000},
            )
        )
        svc.handle(
            Message(
                event_type=Type.DEFAULT_OCCURRED,
                source="test",
                payload={"borrower": "dup_test", "principal": 50000},
            )
        )
        assert len(started) == 1

    def test_health_check_returns_counts(self) -> None:
        bus = LocalBus()
        svc = _recovery(bus=bus)
        bus.start()
        health = svc.health_check()
        assert "active_recoveries" in health
        assert "total_recoveries" in health
