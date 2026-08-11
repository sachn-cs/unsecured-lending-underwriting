# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for new stub services: underwriter, pricing, document, disbursement, collection, settlement."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.collection import Handler as CollectionHandler
from underwrite.services.disbursement import Handler as DisbursementHandler
from underwrite.services.document import Handler as DocumentHandler
from underwrite.services.pricing import Handler as PricingHandler
from underwrite.services.settlement import Handler as SettlementHandler
from underwrite.services.underwriter import Handler as UnderwriterHandler
from underwrite.store import Sqlite


class TestUnderwriterService:
    def test_ignores_unrelated_event(self) -> None:
        svc = UnderwriterHandler(name="underwriter", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_rejects_high_default_probability(self) -> None:
        bus = LocalBus()
        rejected: list[Message] = []
        bus.subscribe(Type.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        svc = UnderwriterHandler(name="underwriter", bus=bus, store=Sqlite(":memory:"))
        bus.start()
        svc.handle(
            Message(
                event_type=Type.UNDERWRITE_REQUEST,
                source="test",
                payload={
                    "application_id": "APP2",
                    "borrower": "bob",
                    "principal": 50000.0,
                    "default_probability": 0.5,
                },
            )
        )
        assert len(rejected) == 1
        assert "default_probability_max" in rejected[0].payload["reasons"][0]

    def test_approves_low_risk_loan(self) -> None:
        bus = LocalBus()
        approved: list[Message] = []
        bus.subscribe(Type.UNDERWRITER_APPROVED, lambda e: approved.append(e))
        svc = UnderwriterHandler(name="underwriter", bus=bus, store=Sqlite(":memory:"))
        bus.start()
        svc.handle(
            Message(
                event_type=Type.UNDERWRITE_REQUEST,
                source="test",
                payload={
                    "application_id": "APP1",
                    "borrower": "alice",
                    "principal": 10000.0,
                    "default_probability": 0.05,
                    "credit_score": 720,
                    "aml_status": "cleared",
                    "kyc_status": "verified",
                },
            )
        )
        assert len(approved) == 1
        assert approved[0].payload["outcome"] == "approved"
        assert approved[0].payload["application_id"] == "APP1"


class TestPricingService:
    def test_ignores_unrelated_event(self) -> None:
        svc = PricingHandler(name="pricing", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_computes_pricing(self) -> None:
        bus = LocalBus()
        computed: list[Message] = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: computed.append(e))
        svc = PricingHandler(name="pricing", bus=bus, store=Sqlite(":memory:"))
        bus.start()
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
        assert len(computed) == 1
        p = computed[0].payload
        assert p["borrower"] == "alice"
        assert p["principal"] == 10000.0
        assert p["interest_rate"] > 0
        assert p["tenure_months"] == 12


class TestDocumentService:
    def test_ignores_unrelated_event(self) -> None:
        svc = DocumentHandler(name="document", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_generates_document_on_approval(self) -> None:
        svc = DocumentHandler(name="document", bus=LocalBus(), store=Sqlite(":memory:"))
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
        svc = DocumentHandler(name="document", bus=LocalBus(), store=Sqlite(":memory:"))
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
        svc = DisbursementHandler(name="disbursement", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_records_disbursement(self) -> None:
        svc = DisbursementHandler(name="disbursement", bus=LocalBus(), store=Sqlite(":memory:"))
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
        svc = CollectionHandler(name="collection", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_records_originated_loan(self) -> None:
        svc = CollectionHandler(name="collection", bus=LocalBus(), store=Sqlite(":memory:"))
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
        svc = CollectionHandler(name="collection", bus=LocalBus(), store=Sqlite(":memory:"))
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
        svc = SettlementHandler(name="settlement", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.handle(Message(event_type="other", source="test", payload={}))

    def test_records_settlement_on_default(self) -> None:
        svc = SettlementHandler(name="settlement", bus=LocalBus(), store=Sqlite(":memory:"))
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
        svc = SettlementHandler(name="settlement", bus=LocalBus(), store=Sqlite(":memory:"))
        for borrower in ["alice", "bob"]:
            svc.handle(
                Message(
                    event_type=Type.DEFAULT_OCCURRED,
                    source="test",
                    payload={"borrower": borrower, "principal": 5000.0},
                )
            )
        assert len(svc.settlements) == 2
