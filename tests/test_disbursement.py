"""Tests for DisbursementService — loan payout processing."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.disbursement.service import DisbursementService


def svc(bus=None) -> DisbursementService:
    return DisbursementService(service_id="disbursement", bus=bus)


class TestDisbursementService:

    def test_processes_disbursement_on_doc_generated(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DISBURSEMENT_PROCESSED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type=EventType.DOCUMENT_GENERATED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 10000,
                      "doc_id": "doc1"
                  }))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert received[0].payload["principal"] == 10000.0

    def test_stores_disbursement_record(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Event(event_type=EventType.DOCUMENT_GENERATED,
                  source="test",
                  payload={
                      "borrower": "bob",
                      "principal": 20000,
                      "doc_id": "doc2"
                  }))
        rec = svc_inst.get("bob")
        assert rec is not None
        assert rec["status"] == "disbursed"

    def test_unknown_borrower_returns_none(self) -> None:
        svc_inst = svc()
        assert svc_inst.get("ghost") is None

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DISBURSEMENT_PROCESSED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0
