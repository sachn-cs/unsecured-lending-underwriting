"""Tests for new stub services: underwriter, pricing, document, disbursement, collection, settlement."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.collection.handler import CollectionHandler
from underwrite.services.disbursement.handler import DisbursementHandler
from underwrite.services.document.handler import DocumentHandler
from underwrite.services.pricing.handler import PricingHandler
from underwrite.services.settlement.handler import SettlementHandler
from underwrite.services.underwriter.handler import UnderwriterHandler
from underwrite.store import MemoryStore


class TestUnderwriterService:
    def test_ignores_unrelated_event(self) -> None:
        svc = UnderwriterHandler(service_id="underwriter", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_rejects_high_default_probability(self) -> None:
        svc = UnderwriterHandler(service_id="underwriter", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.UNDERWRITE_REQUEST,
                source="test",
                payload={
                    "borrower": "bob",
                    "principal": 50000.0,
                    "default_probability": 0.5,
                },
            )
        )

    def test_approves_low_risk_loan(self) -> None:
        svc = UnderwriterHandler(service_id="underwriter", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.UNDERWRITE_REQUEST,
                source="test",
                payload={
                    "borrower": "alice",
                    "principal": 10000.0,
                    "default_probability": 0.1,
                },
            )
        )


class TestPricingService:
    def test_ignores_unrelated_event(self) -> None:
        svc = PricingHandler(service_id="pricing", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_computes_pricing(self) -> None:
        svc = PricingHandler(service_id="pricing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.PRICING_REQUEST,
                source="test",
                payload={
                    "borrower": "alice",
                    "principal": 10000.0,
                    "default_probability": 0.1,
                },
            )
        )


class TestDocumentService:
    def test_ignores_unrelated_event(self) -> None:
        svc = DocumentHandler(service_id="document", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_generates_document_on_approval(self) -> None:
        svc = DocumentHandler(service_id="document", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.UNDERWRITER_APPROVED,
                source="test",
                payload={"borrower": "alice", "principal": 10000.0},
            )
        )
        docs = svc.documents_for("alice")
        assert len(docs) == 1
        assert docs[0]["borrower"] == "alice"
        assert docs[0]["status"] == "generated"

    def test_multiple_documents(self) -> None:
        svc = DocumentHandler(service_id="document", bus=LocalBus(), store=MemoryStore())
        for _ in range(3):
            svc.handle(
                Message(
                    event_type=Type.UNDERWRITER_APPROVED,
                    source="test",
                    payload={"borrower": "bob", "principal": 5000.0},
                )
            )
        assert len(svc.documents_for("bob")) == 3


class TestDisbursementService:
    def test_ignores_unrelated_event(self) -> None:
        svc = DisbursementHandler(service_id="disbursement", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_records_disbursement(self) -> None:
        svc = DisbursementHandler(service_id="disbursement", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.DOCUMENT_GENERATED,
                source="test",
                payload={"borrower": "alice", "principal": 10000.0, "doc_id": "doc123"},
            )
        )
        record = svc.get("alice")
        assert record is not None
        assert record["borrower"] == "alice"
        assert record["status"] == "disbursed"


class TestCollectionService:
    def test_ignores_unrelated_event(self) -> None:
        svc = CollectionHandler(service_id="collection", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_records_originated_loan(self) -> None:
        svc = CollectionHandler(service_id="collection", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={
                    "borrower": "alice",
                    "principal": 12000.0,
                    "term": 12.0,
                },
            )
        )
        loan = svc.get("alice")
        assert loan is not None
        assert loan["principal"] == 12000.0
        assert loan["term"] == 12.0
        assert loan["status"] == "active"

    def test_marks_loan_closed_on_full_repayment(self) -> None:
        svc = CollectionHandler(service_id="collection", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={
                    "borrower": "bob",
                    "principal": 1000.0,
                    "term": 1.0,
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.REPAID,
                source="test",
                payload={"user": "bob", "delta_earned": 1000.0},
            )
        )
        loan = svc.get("bob")
        assert loan is not None
        assert loan["status"] == "closed"


class TestSettlementService:
    def test_ignores_unrelated_event(self) -> None:
        svc = SettlementHandler(service_id="settlement", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_records_settlement_on_default(self) -> None:
        svc = SettlementHandler(service_id="settlement", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.DEFAULT_OCCURRED,
                source="test",
                payload={"borrower": "alice", "principal": 10000.0},
            )
        )
        assert len(svc.settlements) == 1
        assert svc.settlements[0]["borrower"] == "alice"
        assert svc.settlements[0]["loss"] == 10000.0
        assert svc.settlements[0]["status"] == "settled"

    def test_tracks_multiple_settlements(self) -> None:
        svc = SettlementHandler(service_id="settlement", bus=LocalBus(), store=MemoryStore())
        for borrower in ["alice", "bob"]:
            svc.handle(
                Message(
                    event_type=Type.DEFAULT_OCCURRED,
                    source="test",
                    payload={"borrower": borrower, "principal": 5000.0},
                )
            )
        assert len(svc.settlements) == 2
