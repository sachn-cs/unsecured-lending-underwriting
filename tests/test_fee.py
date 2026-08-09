"""Exhaustive tests for FeeHandler."""

from __future__ import annotations

import pytest

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__store__ import MemoryStore
from underwrite.services.fee.handler import FeeHandler


class TestFeeService:
    def test_assesses_fixed_fee(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L1", "fee_type": "late_payment"}))
        keys = svc.store.keys("fee:fee_L1_late_payment_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["amount"] == 25.0
        assert rec["fee_type"] == "late_payment"

    def test_assesses_origination_percentage_fee(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Event(
                event_type="fee.assess",
                source="test",
                payload={"loan_id": "L2", "fee_type": "origination", "principal": 100000},
            )
        )
        keys = svc.store.keys("fee:fee_L2_origination_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["amount"] == 1000.0

    def test_assess_emits_fee_assessed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FEE_ASSESSED, lambda e: received.append(e))
        svc = FeeHandler(service_id="fee", bus=bus, store=MemoryStore())
        bus.start()
        svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L3", "fee_type": "service"}))
        assert len(received) == 1
        assert received[0].payload["fee_type"] == "service"
        assert received[0].payload["amount"] == 5.0

    def test_rejects_unknown_fee_type(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L4", "fee_type": "invalid"}))
        assert len(svc.store.keys("fee:")) == 0

    def test_rejects_empty_loan_id(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "", "fee_type": "late_payment"}))
        assert len(svc.store.keys("fee:")) == 0

    def test_pay_fee_marks_as_paid(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L5", "fee_type": "late_payment"}))
        fee_key = svc.store.keys("fee:fee_L5_late_payment_")[0]
        fee_id = fee_key.replace("fee:", "")
        svc.handle(Event(event_type="fee.pay", source="test", payload={"fee_id": fee_id}))
        rec = svc.store.get(fee_key)
        assert rec is not None
        assert rec["paid"] is True
        assert "paid_at" in rec

    def test_pay_already_paid_fee_noop(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L6", "fee_type": "service"}))
        fee_key = svc.store.keys("fee:fee_L6_service_")[0]
        fee_id = fee_key.replace("fee:", "")
        svc.handle(Event(event_type="fee.pay", source="test", payload={"fee_id": fee_id}))
        svc.handle(Event(event_type="fee.pay", source="test", payload={"fee_id": fee_id}))
        rec = svc.store.get(fee_key)
        assert rec is not None
        assert rec["paid"] is True

    def test_pay_unknown_fee_noop(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="fee.pay", source="test", payload={"fee_id": "nonexistent"}))

    def test_auto_assesses_late_fee_on_overdue(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type=EventType.PAYMENT_OVERDUE, source="test", payload={"loan_id": "L7"}))
        keys = svc.store.keys("fee:fee_L7_late_payment_")
        assert len(keys) >= 1

    def test_auto_assess_emits_fee_assessed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.FEE_ASSESSED, lambda e: received.append(e))
        svc = FeeHandler(service_id="fee", bus=bus, store=MemoryStore())
        bus.start()
        svc.handle(Event(event_type=EventType.PAYMENT_OVERDUE, source="test", payload={"loan_id": "L8"}))
        assert len(received) >= 1
        assert received[0].payload["fee_type"] == "late_payment"

    def test_ignores_unrelated_events(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("fee:")) == 0

    def test_multiple_fees_same_loan(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        for ft in ["late_payment", "service", "prepayment"]:
            svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L9", "fee_type": ft}))
        assert len(svc.store.keys("fee:fee_L9_")) == 3

    def test_non_finite_principal_safe(self) -> None:
        from underwrite.__exceptions__ import ProtocolError

        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        with pytest.raises(ProtocolError, match="must be finite"):
            svc.handle(
                Event(
                    event_type="fee.assess",
                    source="test",
                    payload={"loan_id": "L10", "fee_type": "origination", "principal": float("nan")},
                )
            )

    def test_payment_overdue_without_loan_id_noop(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type=EventType.PAYMENT_OVERDUE, source="test", payload={}))
        assert len(svc.store.keys("fee:")) == 0

    def test_payment_overdue_assesses_late_fee(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type=EventType.PAYMENT_OVERDUE, source="test", payload={"loan_id": "L11"}))
        keys = svc.store.keys("fee:fee_L11_late_payment_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["fee_type"] == "late_payment"
        assert rec["amount"] == 25.0


class TestIndianFeeService:
    def test_penal_interest_assessed(self) -> None:
        svc = FeeHandler(service_id="fee", penal_interest_daily_rate=0.05, max_penal_interest_per_loan=1000.0, bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Event(
                event_type="fee.assess",
                source="test",
                payload={
                    "loan_id": "L100",
                    "fee_type": "penal_interest",
                    "overdue_days": 30,
                    "overdue_amount": 10000.0,
                },
            )
        )
        keys = svc.store.keys("fee:fee_L100_penal_interest_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["fee_type"] == "penal_interest"
        assert rec["amount"] > 0
        # 10000 * 0.0005 * 30 = 150
        assert rec["amount"] == 150.0

    def test_penal_interest_capped(self) -> None:
        svc = FeeHandler(service_id="fee", penal_interest_daily_rate=5.0, max_penal_interest_per_loan=500.0, bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Event(
                event_type="fee.assess",
                source="test",
                payload={
                    "loan_id": "L101",
                    "fee_type": "penal_interest",
                    "overdue_days": 30,
                    "overdue_amount": 100000.0,
                },
            )
        )
        keys = svc.store.keys("fee:fee_L101_penal_interest_")
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["amount"] <= 500.0

    def test_late_payment_percent_assessed(self) -> None:
        svc = FeeHandler(service_id="fee", late_payment_percent=2.0, bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Event(
                event_type="fee.assess",
                source="test",
                payload={
                    "loan_id": "L102",
                    "fee_type": "late_payment_percent",
                    "overdue_amount": 8884.88,
                },
            )
        )
        keys = svc.store.keys("fee:fee_L102_late_payment_percent_")
        assert len(keys) >= 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["amount"] > 0
        # 8884.88 * 2% = 177.70
        assert rec["amount"] == 177.7

    def test_penal_interest_zero_days_no_amount(self) -> None:
        svc = FeeHandler(service_id="fee", penal_interest_daily_rate=0.05, bus=LocalBus(), store=MemoryStore())
        svc.handle(
            Event(
                event_type="fee.assess",
                source="test",
                payload={
                    "loan_id": "L103",
                    "fee_type": "penal_interest",
                    "overdue_days": 0,
                    "overdue_amount": 0.0,
                },
            )
        )
        assert len(svc.store.keys("fee:fee_L103")) == 0

    def test_penal_interest_no_rate_configured(self) -> None:
        svc = FeeHandler(service_id="fee", bus=LocalBus(), store=MemoryStore())  # no penal rate configured
        svc.handle(
            Event(
                event_type="fee.assess",
                source="test",
                payload={
                    "loan_id": "L104",
                    "fee_type": "penal_interest",
                    "overdue_days": 30,
                    "overdue_amount": 10000.0,
                },
            )
        )
        assert len(svc.store.keys("fee:fee_L104")) == 0
