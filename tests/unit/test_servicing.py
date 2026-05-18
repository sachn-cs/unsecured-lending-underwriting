"""Unit tests for loan servicing modules."""

from __future__ import annotations

import pytest

from ulu.domain.loans import RepaymentType
from ulu.servicing.recovery import RecoveryService, RecoveryType
from ulu.servicing.repayments import RepaymentService
from ulu.servicing.schedules import ScheduleType, generate_schedule


class TestGenerateSchedule:
    def test_bullet_schedule(self) -> None:
        schedule = generate_schedule(1000.0, 3, 0.1, ScheduleType.BULLET, periods_per_year=1)
        assert len(schedule) == 3
        assert schedule[0].principal_due == 0.0
        assert schedule[2].principal_due == 1000.0
        assert schedule[0].interest_due == pytest.approx(100.0, abs=0.01)

    def test_interest_only_schedule(self) -> None:
        schedule = generate_schedule(1000.0, 3, 0.1, ScheduleType.INTEREST_ONLY, periods_per_year=1)
        for inst in schedule:
            assert inst.principal_due == 0.0
            assert inst.interest_due == pytest.approx(100.0, abs=0.01)

    def test_amortizing_schedule(self) -> None:
        schedule = generate_schedule(1000.0, 3, 0.1, ScheduleType.AMORTIZING, periods_per_year=1)
        assert len(schedule) == 3
        total_principal = sum(inst.principal_due for inst in schedule)
        assert pytest.approx(total_principal, abs=1.0) == 1000.0
        total_interest = sum(inst.interest_due for inst in schedule)
        assert total_interest > 0

    def test_amortizing_zero_rate(self) -> None:
        schedule = generate_schedule(1000.0, 4, 0.0, ScheduleType.AMORTIZING)
        assert len(schedule) == 4
        for inst in schedule:
            assert inst.principal_due == pytest.approx(250.0, abs=0.01)
            assert inst.interest_due == 0.0

    def test_monthly_periods(self) -> None:
        schedule = generate_schedule(12000.0, 12, 0.12, ScheduleType.AMORTIZING, periods_per_year=12)
        assert len(schedule) == 12
        total_principal = sum(inst.principal_due for inst in schedule)
        assert pytest.approx(total_principal, abs=1.0) == 12000.0

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError):
            generate_schedule(-100, 3, 0.1, ScheduleType.BULLET)
        with pytest.raises(ValueError):
            generate_schedule(1000, 0, 0.1, ScheduleType.BULLET)
        with pytest.raises(ValueError):
            generate_schedule(1000, 3, -0.1, ScheduleType.BULLET)
        with pytest.raises(ValueError):
            generate_schedule(1000, 3, 0.1, ScheduleType.BULLET, periods_per_year=0)


class TestRepaymentService:
    def test_process_repayment_full(self) -> None:
        svc = RepaymentService()
        interest, principal, excess, event = svc.process_repayment(
            "l1", "b1", 500.0, 1000.0, 100.0, RepaymentType.SCHEDULED
        )
        assert interest == 100.0
        assert principal == 400.0
        assert excess == 0.0
        assert event.delta_earned == 400.0

    def test_process_repayment_partial(self) -> None:
        svc = RepaymentService()
        interest, principal, excess, event = svc.process_repayment(
            "l1", "b1", 50.0, 1000.0, 100.0, RepaymentType.PARTIAL
        )
        assert interest == 50.0
        assert principal == 0.0
        assert excess == 0.0

    def test_negative_amount_rejected(self) -> None:
        svc = RepaymentService()
        with pytest.raises(ValueError):
            svc.process_repayment("l1", "b1", -10.0, 1000.0, 100.0)

    def test_overpayment_rejected(self) -> None:
        svc = RepaymentService()
        with pytest.raises(ValueError, match="overpayment"):
            svc.process_repayment("l1", "b1", 2000.0, 1000.0, 100.0)

    def test_negative_principal_rejected(self) -> None:
        svc = RepaymentService()
        with pytest.raises(ValueError, match="non-negative"):
            svc.process_repayment("l1", "b1", 100.0, -10.0, 100.0)

    def test_negative_interest_rejected(self) -> None:
        svc = RepaymentService()
        with pytest.raises(ValueError, match="non-negative"):
            svc.process_repayment("l1", "b1", 100.0, 1000.0, -10.0)


class TestRecoveryService:
    def test_liquidation_recovery(self) -> None:
        svc = RecoveryService()
        recovered, event = svc.initiate_recovery("l1", "b1", 1000.0, RecoveryType.LIQUIDATION, collateral_value=600.0)
        assert recovered == 600.0
        assert event.physical_recovery == 600.0

    def test_write_off_recovery(self) -> None:
        svc = RecoveryService()
        recovered, event = svc.initiate_recovery("l1", "b1", 1000.0, RecoveryType.WRITE_OFF)
        assert recovered == 0.0

    def test_workout_recovery(self) -> None:
        svc = RecoveryService()
        recovered, event = svc.initiate_recovery("l1", "b1", 1000.0, RecoveryType.WORKOUT)
        assert recovered == 500.0
