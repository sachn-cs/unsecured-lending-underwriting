# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Exhaustive tests for Handler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.payment.handler import Handler as PaymentHandler
from underwrite.store import InMemory


class TestPaymentService:
    def test_receive_payment_creates_record(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "L1", "amount": 500}))
        keys = svc.store.keys("payment:pay_L1_")
        assert len(keys) == 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["loan_id"] == "L1"
        assert rec["amount"] == 500

    def test_receive_emits_payment_received(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_RECEIVED, lambda e: received.append(e))
        svc = PaymentHandler(name="payment", bus=bus, store=InMemory())
        bus.start()
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "L1", "amount": 250}))
        assert len(received) == 1
        assert received[0].payload["amount"] == 250
        assert received[0].payload["loan_id"] == "L1"

    def test_rejects_zero_amount(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "L1", "amount": 0}))
        assert len(svc.store.keys("payment:")) == 0

    def test_rejects_empty_loan_id(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "", "amount": 100}))
        assert len(svc.store.keys("payment:")) == 0

    def test_schedule_payment_creates_schedule(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(
                event_type="payment.schedule",
                source="test",
                payload={"loan_id": "L1", "due_date": "2025-01-15", "amount": 1000},
            )
        )
        key = "schedule:L1:2025-01-15"
        rec = svc.store.get(key)
        assert rec is not None
        assert rec["loan_id"] == "L1"
        assert rec["status"] == "pending"

    def test_schedule_emits_payment_due(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_DUE, lambda e: received.append(e))
        svc = PaymentHandler(name="payment", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(
                event_type="payment.schedule",
                source="test",
                payload={"loan_id": "L1", "due_date": "2025-02-01", "amount": 500},
            )
        )
        assert len(received) == 1

    def test_schedule_rejects_missing_due_date(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="payment.schedule", source="test", payload={"loan_id": "L1", "amount": 100}))
        assert len(svc.store.keys("schedule:")) == 0

    def test_check_overdue_detects_late_payments(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        past = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        svc.handle(
            Message(
                event_type="payment.schedule", source="test", payload={"loan_id": "L1", "due_date": past, "amount": 100}
            )
        )
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_OVERDUE, lambda e: received.append(e))
        svc2 = PaymentHandler(name="payment", bus=bus, store=svc.store)
        bus.start()
        svc2.handle(Message(event_type="payment.check_overdue", source="test", payload={"loan_id": "L1"}))
        assert len(received) >= 1
        key = f"schedule:L1:{past}"
        rec = svc2.store.get(key)
        assert rec is not None
        assert rec["status"] == "overdue"

    def test_check_overdue_ignores_recent_payments(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        recent = datetime.now(timezone.utc).isoformat()
        svc.handle(
            Message(
                event_type="payment.schedule",
                source="test",
                payload={"loan_id": "L1", "due_date": recent, "amount": 100},
            )
        )
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_OVERDUE, lambda e: received.append(e))
        svc2 = PaymentHandler(name="payment", bus=bus, store=svc.store)
        bus.start()
        svc2.handle(Message(event_type="payment.check_overdue", source="test", payload={"loan_id": "L1"}))
        assert len(received) == 0

    def test_check_overdue_noop_for_unknown_loan(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="payment.check_overdue", source="test", payload={"loan_id": "NONEXISTENT"}))
        assert len(svc.store.keys("schedule:")) == 0

    def test_ignores_unrelated_events(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("payment:")) == 0

    def test_multiple_payments_same_loan(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "L1", "amount": 100}))
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "L1", "amount": 200}))
        svc.handle(Message(event_type="payment.receive", source="test", payload={"loan_id": "L1", "amount": 300}))
        keys = svc.store.keys("payment:pay_L1_")
        assert len(keys) == 3


class TestPaymentServiceRazorpayBridging:
    def test_razorpay_captured_emits_payment_received(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_RECEIVED, lambda e: received.append(e))
        svc = PaymentHandler(name="payment", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_PAYMENT_CAPTURED,
                source="razorpay",
                payload={
                    "loan_id": "L1",
                    "payment_id": "pay_rzp_001",
                    "amount": 5000.0,
                    "method": "upi",
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L1"
        assert payload["amount"] == 5000.0
        assert payload["payment_id"] == "pay_rzp_001"
        assert payload.get("gateway") == "razorpay"

    def test_razorpay_captured_stores_record(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_PAYMENT_CAPTURED,
                source="razorpay",
                payload={
                    "loan_id": "L2",
                    "payment_id": "pay_rzp_002",
                    "amount": 3000.0,
                },
            )
        )
        rec = svc.store.get("razorpay_payment:pay_rzp_002")
        assert rec is not None
        assert rec["loan_id"] == "L2"
        assert rec["amount"] == 3000.0
        assert rec["status"] == "captured"

    def test_razorpay_captured_no_loan_id_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_RECEIVED, lambda e: received.append(e))
        svc = PaymentHandler(name="payment", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_PAYMENT_CAPTURED,
                source="razorpay",
                payload={
                    "payment_id": "pay_rzp_no_loan",
                    "amount": 1000.0,
                },
            )
        )
        assert len(received) == 0

    def test_razorpay_captured_zero_amount_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_RECEIVED, lambda e: received.append(e))
        svc = PaymentHandler(name="payment", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_PAYMENT_CAPTURED,
                source="razorpay",
                payload={
                    "loan_id": "L3",
                    "payment_id": "pay_rzp_zero",
                    "amount": 0.0,
                },
            )
        )
        assert len(received) == 0

    def test_razorpay_subscription_charged_emits_payment_received(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PAYMENT_RECEIVED, lambda e: received.append(e))
        svc = PaymentHandler(name="payment", bus=bus, store=InMemory())
        bus.start()
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_SUBSCRIPTION_CHARGED,
                source="razorpay",
                payload={
                    "loan_id": "L10",
                    "subscription_id": "sub_monthly",
                    "payment_id": "pay_sub_001",
                    "amount": 2500.0,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L10"
        assert payload["amount"] == 2500.0
        assert payload.get("subscription_id") == "sub_monthly"

    def test_razorpay_subscription_charged_stores_record(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_SUBSCRIPTION_CHARGED,
                source="razorpay",
                payload={
                    "loan_id": "L11",
                    "subscription_id": "sub_emi",
                    "payment_id": "pay_sub_002",
                    "amount": 4500.0,
                },
            )
        )
        rec = svc.store.get("razorpay_subscription:pay_sub_002")
        assert rec is not None
        assert rec["loan_id"] == "L11"
        assert rec["amount"] == 4500.0
        assert rec["status"] == "charged"

    def test_razorpay_refund_stores_record(self) -> None:
        svc = PaymentHandler(name="payment", bus=LocalBus(), store=InMemory())
        svc.handle(
            Message(
                event_type=Type.RAZORPAY_PAYMENT_REFUNDED,
                source="razorpay",
                payload={
                    "loan_id": "L20",
                    "payment_id": "pay_refund_001",
                    "amount": 1000.0,
                },
            )
        )
        rec = svc.store.get("razorpay_refund:pay_refund_001")
        assert rec is not None
        assert rec["loan_id"] == "L20"
        assert rec["amount"] == 1000.0
        assert rec["status"] == "refunded"
