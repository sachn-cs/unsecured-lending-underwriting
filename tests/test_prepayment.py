"""Tests for PrepaymentHandler — foreclosure/prepayment workflow."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.prepayment.handler import PrepaymentHandler


def svc(bus=None) -> PrepaymentHandler:
    return PrepaymentHandler(service_id="prepayment", bus=bus)


class TestPrepaymentService:
    def test_prepayment_request_missing_loan_id_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FORECLOSURE_COMPUTED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Event(event_type=EventType.PREPAYMENT_REQUEST, source="test", payload={}))
        assert len(received) == 0

    def test_prepayment_request_computes_foreclosure(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FORECLOSURE_COMPUTED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(
                event_type=EventType.PREPAYMENT_REQUEST,
                source="test",
                payload={
                    "loan_id": "L1",
                    "principal": 100000,
                    "annual_rate": 12,
                    "tenure_months": 12,
                    "payments": [{"date": "2025-02-01", "amount": 8884.88}],
                },
            )
        )
        assert len(received) == 1
        quote = received[0].payload
        assert quote["loan_id"] == "L1"
        assert quote["total_due"] > 90000
        assert quote["savings"] >= 0

    def test_prepayment_with_penalty(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FORECLOSURE_COMPUTED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(
                event_type=EventType.PREPAYMENT_REQUEST,
                source="test",
                payload={
                    "loan_id": "L2",
                    "principal": 100000,
                    "annual_rate": 12,
                    "tenure_months": 12,
                    "penalty_rate": 3,
                },
            )
        )
        assert len(received) == 1
        quote = received[0].payload
        assert quote["penalty"] > 0
        assert quote["penalty_rate"] == 3

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FORECLOSURE_COMPUTED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0
