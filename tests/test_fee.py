"""Exhaustive tests for FeeService."""
from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.fee.service import FeeService


class TestFeeService:

    def test_assesses_fixed_fee(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "fee_type": "late_payment"
                  }))
        keys = svc.store.keys("fee:fee_L1_late_payment_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec["amount"] == 25.0
        assert rec["fee_type"] == "late_payment"

    def test_assesses_origination_percentage_fee(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "L2",
                      "fee_type": "origination",
                      "principal": 100000
                  }))
        keys = svc.store.keys("fee:fee_L2_origination_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec["amount"] == 1000.0

    def test_assess_emits_fee_assessed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FEE_ASSESSED, lambda e: received.append(e))
        svc = FeeService(service_id="fee", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "L3",
                      "fee_type": "service"
                  }))
        assert len(received) == 1
        assert received[0].payload["fee_type"] == "service"
        assert received[0].payload["amount"] == 5.0

    def test_rejects_unknown_fee_type(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "L4",
                      "fee_type": "invalid"
                  }))
        assert len(svc.store.keys("fee:")) == 0

    def test_rejects_empty_loan_id(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "",
                      "fee_type": "late_payment"
                  }))
        assert len(svc.store.keys("fee:")) == 0

    def test_pay_fee_marks_as_paid(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "L5",
                      "fee_type": "late_payment"
                  }))
        fee_key = svc.store.keys("fee:fee_L5_late_payment_")[0]
        fee_id = fee_key.replace("fee:", "")
        svc.handle(
            Event(event_type="fee.pay",
                  source="test",
                  payload={"fee_id": fee_id}))
        rec = svc.store.get(fee_key)
        assert rec["paid"] is True
        assert "paid_at" in rec

    def test_pay_already_paid_fee_noop(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.assess",
                  source="test",
                  payload={
                      "loan_id": "L6",
                      "fee_type": "service"
                  }))
        fee_key = svc.store.keys("fee:fee_L6_service_")[0]
        fee_id = fee_key.replace("fee:", "")
        svc.handle(
            Event(event_type="fee.pay",
                  source="test",
                  payload={"fee_id": fee_id}))
        svc.handle(
            Event(event_type="fee.pay",
                  source="test",
                  payload={"fee_id": fee_id}))
        rec = svc.store.get(fee_key)
        assert rec["paid"] is True

    def test_pay_unknown_fee_noop(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type="fee.pay",
                  source="test",
                  payload={"fee_id": "nonexistent"}))

    def test_auto_assesses_late_fee_on_overdue(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(
            Event(event_type=EventType.PAYMENT_OVERDUE,
                  source="test",
                  payload={"loan_id": "L7"}))
        keys = svc.store.keys("fee:fee_L7_late_payment_")
        assert len(keys) >= 1

    def test_auto_assess_emits_fee_assessed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FEE_ASSESSED, lambda e: received.append(e))
        svc = FeeService(service_id="fee", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.PAYMENT_OVERDUE,
                  source="test",
                  payload={"loan_id": "L8"}))
        assert len(received) >= 1
        assert received[0].payload["fee_type"] == "late_payment"

    def test_ignores_unrelated_events(self) -> None:
        svc = FeeService(service_id="fee")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("fee:")) == 0

    def test_multiple_fees_same_loan(self) -> None:
        svc = FeeService(service_id="fee")
        for ft in ["late_payment", "service", "prepayment"]:
            svc.handle(
                Event(event_type="fee.assess",
                      source="test",
                      payload={
                          "loan_id": "L9",
                          "fee_type": ft
                      }))
        assert len(svc.store.keys("fee:fee_L9_")) == 3
