"""Tests for SettlementHandler — loss recognition and final accounting."""

from __future__ import annotations

import pytest

from underwrite.events import Event, EventType
from underwrite.local import LocalBus
from underwrite.services.settlement.handler import SettlementHandler
from underwrite.store import MemoryStore


def svc(bus=None) -> SettlementHandler:
    return SettlementHandler(service_id="settlement", bus=bus or LocalBus(), store=MemoryStore())


class TestSettlementService:
    def test_records_loss_on_default(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.SETTLEMENT_COMPLETED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "alice", "principal": 50000}
            )
        )
        assert len(received) == 1
        assert received[0].payload["loss"] == 50000.0

    def test_appends_to_settlements_list(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "bob", "principal": 30000})
        )
        assert len(svc_inst.settlements) == 1
        assert svc_inst.settlements[0]["loss"] == 30000.0

    def test_multiple_defaults(self) -> None:
        svc_inst = svc()
        for i in range(5):
            svc_inst.handle(
                Event(
                    event_type=EventType.DEFAULT_OCCURRED,
                    source="test",
                    payload={"borrower": f"b{i}", "principal": 10000},
                )
            )
        assert len(svc_inst.settlements) == 5

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.SETTLEMENT_COMPLETED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0

    def test_empty_payload_no_crash(self) -> None:
        from underwrite.exceptions import ProtocolError

        svc_inst = svc()
        with pytest.raises(ProtocolError):
            svc_inst.handle(Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={}))
