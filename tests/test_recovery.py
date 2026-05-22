"""Tests for RecoveryService — post-default recovery orchestration.

Tests verify behavior through emitted RECOVERY_STARTED and RECOVERY_COMPLETED events.
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.recovery.service import RecoveryService


def recovery(bus=None) -> RecoveryService:
    return RecoveryService(service_id="recovery", bus=bus)


class TestRecoveryService:

    def test_emits_started_on_default(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RECOVERY_STARTED, lambda e: received.append(e))
        svc = recovery(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 50000
                  }))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert received[0].payload["principal"] == 50000.0
        assert "started_at" in received[0].payload

    def test_emits_completed_with_recovery_amount(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RECOVERY_COMPLETED,
                      lambda e: received.append(e))
        svc = recovery(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "bob",
                      "principal": 100000
                  }))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "bob"
        assert received[0].payload["recovered"] == 30000.0
        assert received[0].payload["outstanding"] == 70000.0

    def test_emits_both_events_for_default(self) -> None:
        bus = LocalBus()
        all_events: list[Event] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        svc = recovery(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "carol",
                      "principal": 50000
                  }))
        types = [e.event_type for e in all_events]
        assert EventType.RECOVERY_STARTED in types
        assert EventType.RECOVERY_COMPLETED in types

    def test_zero_principal_default(self) -> None:
        bus = LocalBus()
        completed: list[Event] = []
        bus.subscribe(EventType.RECOVERY_COMPLETED,
                      lambda e: completed.append(e))
        svc = recovery(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "dave",
                      "principal": 0
                  }))
        assert completed[0].payload["recovered"] == 0.0
        assert completed[0].payload["outstanding"] == 0.0

    def test_principal_defaults_to_zero(self) -> None:
        bus = LocalBus()
        started: list[Event] = []
        bus.subscribe(EventType.RECOVERY_STARTED, lambda e: started.append(e))
        svc = recovery(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={"borrower": "eve"}))
        assert started[0].payload["principal"] == 0.0

    def test_ignores_non_default_events(self) -> None:
        bus = LocalBus()
        started: list[Event] = []
        bus.subscribe(EventType.RECOVERY_STARTED, lambda e: started.append(e))
        svc = recovery(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={}))
        assert len(started) == 0
