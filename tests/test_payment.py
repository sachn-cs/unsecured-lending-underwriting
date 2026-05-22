"""Exhaustive tests for PaymentService."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.payment.service import PaymentService


class TestPaymentService:

    def test_receive_payment_creates_record(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 500
                  }))
        keys = svc.store.keys("payment:pay_L1_")
        assert len(keys) == 1
        rec = svc.store.get(keys[0])
        assert rec["loan_id"] == "L1"
        assert rec["amount"] == 500

    def test_receive_emits_payment_received(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PAYMENT_RECEIVED, lambda e: received.append(e))
        svc = PaymentService(service_id="payment", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 250
                  }))
        assert len(received) == 1
        assert received[0].payload["amount"] == 250
        assert received[0].payload["loan_id"] == "L1"

    def test_rejects_zero_amount(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 0
                  }))
        assert len(svc.store.keys("payment:")) == 0

    def test_rejects_empty_loan_id(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "",
                      "amount": 100
                  }))
        assert len(svc.store.keys("payment:")) == 0

    def test_schedule_payment_creates_schedule(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.schedule",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "due_date": "2025-01-15",
                      "amount": 1000
                  }))
        key = "schedule:L1:2025-01-15"
        rec = svc.store.get(key)
        assert rec["loan_id"] == "L1"
        assert rec["status"] == "pending"

    def test_schedule_emits_payment_due(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PAYMENT_DUE, lambda e: received.append(e))
        svc = PaymentService(service_id="payment", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="payment.schedule",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "due_date": "2025-02-01",
                      "amount": 500
                  }))
        assert len(received) == 1

    def test_schedule_rejects_missing_due_date(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.schedule",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 100
                  }))
        assert len(svc.store.keys("schedule:")) == 0

    def test_check_overdue_detects_late_payments(self) -> None:
        svc = PaymentService(service_id="payment")
        past = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        svc.handle(
            Event(event_type="payment.schedule",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "due_date": past,
                      "amount": 100
                  }))
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PAYMENT_OVERDUE, lambda e: received.append(e))
        svc2 = PaymentService(service_id="payment", bus=bus, store=svc.store)
        bus.start()
        svc2.handle(
            Event(event_type="payment.check_overdue",
                  source="test",
                  payload={"loan_id": "L1"}))
        assert len(received) >= 1
        key = f"schedule:L1:{past}"
        rec = svc2.store.get(key)
        assert rec["status"] == "overdue"

    def test_check_overdue_ignores_recent_payments(self) -> None:
        svc = PaymentService(service_id="payment")
        recent = datetime.now(timezone.utc).isoformat()
        svc.handle(
            Event(event_type="payment.schedule",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "due_date": recent,
                      "amount": 100
                  }))
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PAYMENT_OVERDUE, lambda e: received.append(e))
        svc2 = PaymentService(service_id="payment", bus=bus, store=svc.store)
        bus.start()
        svc2.handle(
            Event(event_type="payment.check_overdue",
                  source="test",
                  payload={"loan_id": "L1"}))
        assert len(received) == 0

    def test_check_overdue_noop_for_unknown_loan(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.check_overdue",
                  source="test",
                  payload={"loan_id": "NONEXISTENT"}))
        assert len(svc.store.keys("schedule:")) == 0

    def test_ignores_unrelated_events(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("payment:")) == 0

    def test_multiple_payments_same_loan(self) -> None:
        svc = PaymentService(service_id="payment")
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 100
                  }))
        import time as time_mod
        time_mod.sleep(1.1)
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 200
                  }))
        time_mod.sleep(1.1)
        svc.handle(
            Event(event_type="payment.receive",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "amount": 300
                  }))
        keys = svc.store.keys("payment:pay_L1_")
        assert len(keys) == 3
