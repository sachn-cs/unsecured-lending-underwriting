"""Tests for SettlementService — loss recognition and final accounting."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.settlement.service import SettlementService


def svc(bus=None) -> SettlementService:
    return SettlementService(service_id="settlement", bus=bus)


class TestSettlementService:

    def test_records_loss_on_default(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.SETTLEMENT_COMPLETED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 50000
                  }))
        assert len(received) == 1
        assert received[0].payload["loss"] == 50000.0

    def test_appends_to_settlements_list(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "bob",
                      "principal": 30000
                  }))
        assert len(svc_inst.settlements) == 1
        assert svc_inst.settlements[0]["loss"] == 30000.0

    def test_multiple_defaults(self) -> None:
        svc_inst = svc()
        for i in range(5):
            svc_inst.handle(
                Event(event_type=EventType.DEFAULT_OCCURRED,
                      source="test",
                      payload={
                          "borrower": f"b{i}",
                          "principal": 10000
                      }))
        assert len(svc_inst.settlements) == 5

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.SETTLEMENT_COMPLETED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0

    def test_empty_payload_no_crash(self) -> None:
        from underwrite.__exceptions__ import ProtocolError
        svc_inst = svc()
        try:
            svc_inst.handle(
                Event(event_type=EventType.DEFAULT_OCCURRED,
                      source="test",
                      payload={}))
        except ProtocolError:
            pass
