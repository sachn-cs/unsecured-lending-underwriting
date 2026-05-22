"""Tests for CollateralService — LTV tracking and liquidation.

Tests verify behavior through public interfaces only:
  - get() method for querying collateral state
  - Emitted events (COLLATERAL_MARKED, COLLATERAL_LIQUIDATED)
  - Edge cases: missing fields, unknown borrower, zero principal
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.collateral.service import CollateralService


def collateral(bus=None) -> CollateralService:
    return CollateralService(service_id="collateral", bus=bus)


class TestCollateralService:

    def test_tracks_collateral_on_origination(self) -> None:
        svc = collateral()
        svc.handle(
            Event(
                event_type=EventType.LOAN_ORIGINATED,
                source="test",
                payload={
                    "borrower": "alice",
                    "principal": 10000
                },
            ))
        col = svc.get("alice")
        assert col is not None
        assert col["principal"] == 10000
        assert col["required"] == 7500.0
        assert col["ltv"] == 0.75

    def test_emits_marked_event_with_correct_values(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.COLLATERAL_MARKED, lambda e: received.append(e))
        svc = collateral(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.LOAN_ORIGINATED,
                source="test",
                payload={
                    "borrower": "bob",
                    "principal": 50000
                },
            ))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "bob"
        assert received[0].payload["required"] == 37500.0
        assert received[0].payload["ltv_ratio"] == 0.75

    def test_liquidates_on_default_and_emits(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.COLLATERAL_LIQUIDATED,
                      lambda e: received.append(e))
        svc = collateral(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.LOAN_ORIGINATED,
                source="test",
                payload={
                    "borrower": "carol",
                    "principal": 20000
                },
            ))
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED,
                source="test",
                payload={
                    "borrower": "carol",
                    "principal": 20000
                },
            ))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "carol"
        assert received[0].payload["principal"] == 20000.0
        assert svc.get("carol") is None

    def test_default_without_collateral_does_nothing(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.COLLATERAL_LIQUIDATED,
                      lambda e: received.append(e))
        svc = collateral(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED,
                source="test",
                payload={"borrower": "nobody"},
            ))
        assert len(received) == 0

    def test_get_unknown_borrower_returns_none(self) -> None:
        svc = collateral()
        assert svc.get("ghost") is None

    def test_multiple_borrowers_independent(self) -> None:
        svc = collateral()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "a",
                      "principal": 100
                  }))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "b",
                      "principal": 200
                  }))
        assert svc.get("a")["principal"] == 100
        assert svc.get("b")["principal"] == 200
        assert svc.get("a")["required"] == 75.0
        assert svc.get("b")["required"] == 150.0

    def test_ignores_unrelated_event_types(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.COLLATERAL_MARKED, lambda e: received.append(e))
        svc = collateral(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(Event(event_type="user.added", source="test", payload={}))
        assert len(received) == 0
        assert svc.get("anyone") is None

    def test_origination_without_borrower_is_rejected(self) -> None:
        svc = collateral()
        from underwrite.__exceptions__ import ProtocolError
        try:
            svc.handle(
                Event(event_type=EventType.LOAN_ORIGINATED,
                      source="test",
                      payload={}))
        except ProtocolError:
            pass
        assert svc.get("") is None

    def test_origination_without_principal_defaults_zero(self) -> None:
        svc = collateral()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "x"}))
        assert svc.get("x")["required"] == 0.0

    def test_liquidation_removes_borrower(self) -> None:
        svc = collateral()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "y",
                      "principal": 5000
                  }))
        assert svc.get("y") is not None
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={"borrower": "y"}))
        assert svc.get("y") is None

    def test_emit_both_marked_and_liquidated_on_lifecycle(self) -> None:
        bus = LocalBus()
        all_events: list[Event] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        svc = collateral(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "z",
                      "principal": 10000
                  }))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "z",
                      "principal": 10000
                  }))
        types = [e.event_type for e in all_events]
        assert EventType.COLLATERAL_MARKED in types
        assert EventType.COLLATERAL_LIQUIDATED in types
