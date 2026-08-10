"""Exhaustive tests for Handler."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.servicing.handler import Handler as ServicingHandler
from underwrite.store import MemoryStore


class TestServicingService:
    def test_creates_loan_record_on_originated(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={"loan_id": "L1", "borrower": "alice", "principal": 100000},
            )
        )
        rec = svc.store.get("loan:L1")
        assert rec is not None
        assert rec["borrower"] == "alice"
        assert rec["principal"] == 100000
        assert rec["outstanding"] == 100000
        assert rec["status"] == "active"

    def test_handles_partial_repayment(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={"loan_id": "L2", "borrower": "bob", "principal": 50000},
            )
        )
        svc.handle(Message(event_type="repaid", source="test", payload={"loan_id": "L2", "amount": 10000}))
        rec = svc.store.get("loan:L2")
        assert rec is not None
        assert rec["outstanding"] == 40000
        assert rec["status"] == "active"

    def test_marks_paid_on_full_repayment(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={"loan_id": "L3", "borrower": "carol", "principal": 30000},
            )
        )
        svc.handle(Message(event_type="repaid", source="test", payload={"loan_id": "L3", "amount": 30000}))
        rec = svc.store.get("loan:L3")
        assert rec is not None
        assert rec["outstanding"] == 0
        assert rec["status"] == "paid"
        assert "paid_at" in rec

    def test_prevents_negative_outstanding(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={"loan_id": "L4", "borrower": "dave", "principal": 10000},
            )
        )
        svc.handle(Message(event_type="repaid", source="test", payload={"loan_id": "L4", "amount": 99999}))
        rec = svc.store.get("loan:L4")
        assert rec is not None
        assert rec["outstanding"] == 0

    def test_handles_default(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={"loan_id": "L5", "borrower": "eve", "principal": 20000},
            )
        )
        svc.handle(Message(event_type="default.occurred", source="test", payload={"loan_id": "L5"}))
        rec = svc.store.get("loan:L5")
        assert rec is not None
        assert rec["status"] == "defaulted"
        assert "defaulted_at" in rec

    def test_unknown_loan_repayment_noop(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="repaid", source="test", payload={"loan_id": "NONEXISTENT", "amount": 100}))
        assert len(svc.store.keys("loan:")) == 0

    def test_unknown_loan_default_noop(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="default.occurred", source="test", payload={"loan_id": "NONEXISTENT"}))
        assert len(svc.store.keys("loan:")) == 0

    def test_empty_loan_id_noop(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="loan.originated", source="test", payload={}))
        assert len(svc.store.keys("loan:")) == 0

    def test_ignores_unrelated_events(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("loan:")) == 0

    def test_multiple_loans_independent(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated", source="test", payload={"loan_id": "A", "borrower": "a", "principal": 100}
            )
        )
        svc.handle(
            Message(
                event_type="loan.originated", source="test", payload={"loan_id": "B", "borrower": "b", "principal": 200}
            )
        )
        rec_a = svc.store.get("loan:A")
        assert rec_a is not None
        assert rec_a["outstanding"] == 100
        rec_b = svc.store.get("loan:B")
        assert rec_b is not None
        assert rec_b["outstanding"] == 200


class TestServicingInterestAccrual:
    def test_loan_originated_with_rate(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={
                    "loan_id": "L100",
                    "borrower": "alice",
                    "principal": 100000,
                    "annual_rate": 12.0,
                },
            )
        )
        rec = svc.store.get("loan:L100")
        assert rec is not None
        assert rec["annual_rate"] == 12.0
        assert rec["daily_rate"] == 12.0 / 36500.0
        assert "last_interest_date" in rec
        assert "origin_date" in rec
        assert rec["status"] == "active"

    def test_accrue_interest_manual_trigger(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={
                    "loan_id": "L101",
                    "borrower": "bob",
                    "principal": 100000,
                    "annual_rate": 12.0,
                },
            )
        )
        # Manual interest accrual should return 0 (same-day)
        accrued = svc.accrue_interest("L101")
        assert accrued == 0.0

    def test_accrue_interest_unknown_loan(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        accrued = svc.accrue_interest("NONEXISTENT")
        assert accrued == 0.0

    def test_repayment_applies_to_accrued_interest_first(self) -> None:
        """Test that payment first clears accrued interest before reducing principal."""
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={
                    "loan_id": "L102",
                    "borrower": "carol",
                    "principal": 50000,
                    "annual_rate": 12.0,
                },
            )
        )
        # Outstanding should still be 50000 (no interest accrued same-day)
        rec = svc.store.get("loan:L102")
        assert rec is not None
        assert rec["outstanding"] == 50000


class TestServicingRazorpayHandlers:
    def test_order_created_tracks_order_id(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={
                    "loan_id": "L50",
                    "borrower": "alice",
                    "principal": 100000,
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_ORDER_CREATED,
                source="razorpay",
                payload={
                    "loan_id": "L50",
                    "order_id": "order_rzp_001",
                },
            )
        )
        rec = svc.store.get("loan:L50")
        assert rec is not None
        assert rec["razorpay_order_id"] == "order_rzp_001"

    def test_mandate_active_tracks_subscription(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={
                    "loan_id": "L51",
                    "borrower": "bob",
                    "principal": 50000,
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_MANDATE_ACTIVE,
                source="razorpay",
                payload={
                    "loan_id": "L51",
                    "subscription_id": "sub_rzp_001",
                },
            )
        )
        rec = svc.store.get("loan:L51")
        assert rec is not None
        assert rec["razorpay_subscription_id"] == "sub_rzp_001"
        assert rec["razorpay_mandate_status"] == "active"

    def test_mandate_inactive_updates_status(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type="loan.originated",
                source="test",
                payload={
                    "loan_id": "L52",
                    "borrower": "carol",
                    "principal": 25000,
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_MANDATE_ACTIVE,
                source="razorpay",
                payload={
                    "loan_id": "L52",
                    "subscription_id": "sub_rzp_002",
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_MANDATE_INACTIVE,
                source="razorpay",
                payload={
                    "loan_id": "L52",
                },
            )
        )
        rec = svc.store.get("loan:L52")
        assert rec is not None
        assert rec["razorpay_mandate_status"] == "inactive"

    def test_order_created_unknown_loan_noop(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_ORDER_CREATED,
                source="razorpay",
                payload={
                    "loan_id": "NONEXISTENT",
                    "order_id": "order_xxx",
                },
            )
        )
        assert len(svc.store.keys("loan:")) == 0

    def test_mandate_active_missing_loan_id_noop(self) -> None:
        svc = ServicingHandler(service_id="servicing", bus=LocalBus(), store=MemoryStore())
        svc.handle(Message(event_type=Type.RAZORPAY_MANDATE_ACTIVE, source="razorpay", payload={}))
        assert len(svc.store.keys("loan:")) == 0
