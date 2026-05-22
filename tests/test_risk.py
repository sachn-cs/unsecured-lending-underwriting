"""Tests for RiskService — ML scoring and early-warning signals.

Tests verify behavior through emitted events:
  - RISK_EARLY_WARNING on default_probability > 0.3
  - Edge cases: boundary values, missing fields, non-loan events
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__exceptions__ import ProtocolError
from underwrite.services.risk.service import RiskService


def risk(bus=None) -> RiskService:
    return RiskService(service_id="risk", bus=bus)


class TestEarlyWarning:

    def test_warning_on_high_default_probability(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "default_probability": 0.45,
                      "principal": 10000
                  }))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert received[0].payload["default_probability"] == 0.45

    def test_no_warning_on_low_default_probability(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "bob",
                      "default_probability": 0.05,
                      "principal": 10000
                  }))
        assert len(received) == 0

    def test_no_warning_at_exactly_thirty_percent(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "carol",
                      "default_probability": 0.30,
                      "principal": 10000
                  }))
        assert len(received) == 0

    def test_warning_just_above_thirty_percent(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "dave",
                      "default_probability": 0.3001,
                      "principal": 10000
                  }))
        assert len(received) == 1

    def test_warning_at_one_hundred_percent(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "eve",
                      "default_probability": 1.0,
                      "principal": 10000
                  }))
        assert len(received) == 1

    def test_missing_default_probability_no_warning(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "frank",
                      "principal": 10000
                  }))
        assert len(received) == 0

    def test_string_default_probability_parsed(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "grace",
                      "default_probability": "0.50",
                      "principal": 10000
                  }))
        assert len(received) == 1


class TestEdgeCases:

    def test_no_model_no_crash(self) -> None:
        svc = risk()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "heidi",
                      "default_probability": 0.02,
                      "principal": 10000
                  }))

    def test_ignores_non_loan_events(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.RISK_EARLY_WARNING,
                      lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(Event(event_type=EventType.REPAID, source="test",
                         payload={}))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={}))
        assert len(received) == 0

    def test_empty_payload_no_crash(self) -> None:
        svc = risk()
        try:
            svc.handle(
                Event(event_type=EventType.LOAN_ORIGINATED,
                      source="test",
                      payload={}))
        except ProtocolError:
            pass
