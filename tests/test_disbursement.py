"""Tests for Handler — loan payout processing."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.disbursement.handler import Handler
from underwrite.services.disbursement.handler import Handler as DisbursementHandler
from underwrite.store import MemoryStore


def svc(bus=None) -> Handler:
    return DisbursementHandler(service_id="disbursement", bus=bus or LocalBus(), store=MemoryStore())


class TestDisbursementService:
    def test_processes_disbursement_on_doc_generated(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.DISBURSEMENT_PROCESSED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.DOCUMENT_GENERATED,
                source="test",
                payload={"borrower": "alice", "principal": 10000, "doc_id": "doc1"},
            )
        )
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert received[0].payload["principal"] == 10000.0

    def test_stores_disbursement_record(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Message(
                event_type=Type.DOCUMENT_GENERATED,
                source="test",
                payload={"borrower": "bob", "principal": 20000, "doc_id": "doc2"},
            )
        )
        rec = svc_inst.get("bob")
        assert rec is not None
        assert rec["status"] == "disbursed"

    def test_unknown_borrower_returns_none(self) -> None:
        svc_inst = svc()
        assert svc_inst.get("ghost") is None

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.DISBURSEMENT_PROCESSED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0
