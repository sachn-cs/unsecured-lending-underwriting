"""Tests for the EMI amortization engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from underwrite.amortization import (
    AmortizationSchedule,
    EMIScheduleEntry,
    ForeclosureQuote,
    OutstandingBreakdown,
    calculate_emi,
    calculate_foreclosure,
    generate_schedule,
    project_outstanding,
)


class TestCalculateEMI:
    def test_basic_emi(self) -> None:
        assert calculate_emi(Decimal("100000"), Decimal("12"), 12) == Decimal("8884.88")

    def test_fractional_rate(self) -> None:
        assert calculate_emi(Decimal("50000"), Decimal("10.5"), 24) == Decimal("2318.80")

    def test_total_repayment_exceeds_principal(self) -> None:
        p, r, n = Decimal("200000"), Decimal("9"), 60
        emi = calculate_emi(p, r, n)
        total = emi * n
        assert total > p

    def test_large_principal(self) -> None:
        assert calculate_emi(Decimal("10000000"), Decimal("15"), 120) == Decimal("161334.96")

    def test_zero_principal_raises(self) -> None:
        with pytest.raises(ValueError, match="principal must be positive"):
            calculate_emi(Decimal("0"), Decimal("10"), 12)

    def test_negative_principal_raises(self) -> None:
        with pytest.raises(ValueError, match="principal must be positive"):
            calculate_emi(Decimal("-1000"), Decimal("10"), 12)

    def test_zero_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="annual_rate must be positive"):
            calculate_emi(Decimal("1000"), Decimal("0"), 12)

    def test_zero_tenure_raises(self) -> None:
        with pytest.raises(ValueError, match="tenure_months must be positive"):
            calculate_emi(Decimal("1000"), Decimal("10"), 0)

    def test_negative_tenure_raises(self) -> None:
        with pytest.raises(ValueError, match="tenure_months must be positive"):
            calculate_emi(Decimal("1000"), Decimal("10"), -1)


class TestGenerateSchedule:
    def test_length_matches_tenure(self) -> None:
        assert len(generate_schedule(Decimal("100000"), Decimal("12"), 12).entries) == 12

    def test_outstanding_reduces_to_zero(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        assert sched.entries[-1].outstanding_principal == Decimal("0")

    def test_total_repayment_close_to_emi_sum(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        emi_total = sched.emi * 12
        assert abs(emi_total - sched.total_repayment) <= Decimal("0.05")

    def test_interest_declines(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        for i in range(1, len(sched.entries)):
            assert sched.entries[i].interest_component <= sched.entries[i - 1].interest_component

    def test_principal_increases(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        for i in range(1, len(sched.entries)):
            assert sched.entries[i].principal_component >= sched.entries[i - 1].principal_component

    def test_custom_emi_override(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12, emi_override=Decimal("10000"))
        assert sched.emi == Decimal("10000")

    def test_emi_override_last_entry_clears(self) -> None:
        sched = generate_schedule(Decimal("50000"), Decimal("12"), 12, emi_override=Decimal("10000"))
        assert sched.emi == Decimal("10000")
        assert len(sched.entries) == 12
        assert sched.entries[-1].outstanding_principal == Decimal("0")

    def test_custom_start_date(self) -> None:
        start = date(2025, 6, 15)
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 3, start_date=start)
        assert sched.entries[0].due_date == start

    def test_dates_monotonically_increasing(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 24)
        for i in range(1, len(sched.entries)):
            assert sched.entries[i].due_date > sched.entries[i - 1].due_date

    def test_emi_matches_formula(self) -> None:
        p, r, n = Decimal("100000"), Decimal("12"), 12
        expected_emi = calculate_emi(p, r, n)
        assert generate_schedule(p, r, n).emi == expected_emi

    def test_to_dict_snapshot(self) -> None:
        sched = generate_schedule(Decimal("50000"), Decimal("10"), 5)
        d = sched.to_dict()
        assert d["principal"] == 50000.0
        assert d["annual_interest_rate"] == 10.0
        assert d["tenure_months"] == 5
        assert len(d["entries"]) == 5
        assert d["total_repayment"] > 50000.0

    def test_small_principal(self) -> None:
        sched = generate_schedule(Decimal("500"), Decimal("12"), 3)
        assert sched.entries[-1].outstanding_principal == Decimal("0")

    def test_large_tenure(self) -> None:
        sched = generate_schedule(Decimal("1000000"), Decimal("9"), 240)
        assert len(sched.entries) == 240
        assert sched.entries[-1].outstanding_principal == Decimal("0")

    def test_interest_plus_principal_close_to_emi(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        for entry in sched.entries:
            total = entry.interest_component + entry.principal_component
            assert total <= entry.emi_amount + Decimal("0.01")

    def test_first_entry_state(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        first = sched.entries[0]
        assert first.instalment_no == 1
        assert first.outstanding_principal < sched.principal

    def test_last_entry_state(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        last = sched.entries[-1]
        assert last.instalment_no == 12
        assert last.outstanding_principal == Decimal("0")
        assert last.total_interest_paid == sched.total_interest

    def test_total_interest_positive(self) -> None:
        assert generate_schedule(Decimal("100000"), Decimal("12"), 12).total_interest > Decimal("0")

    def test_zero_principal_raises(self) -> None:
        with pytest.raises(ValueError):
            generate_schedule(Decimal("0"), Decimal("10"), 12)


class TestProjectOutstanding:
    def test_no_payments_full_outstanding(self) -> None:
        result = project_outstanding(Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1))
        assert result.total_outstanding == Decimal("100000")

    def test_full_repayment_zero_outstanding(self) -> None:
        result = project_outstanding(
            Decimal("100000"), Decimal("12"), 12, [(date(2025, 2, 1), Decimal("101000"))], as_of=date(2025, 3, 1)
        )
        assert result.total_outstanding == Decimal("0")

    def test_partial_payment_reduces_principal(self) -> None:
        result = project_outstanding(
            Decimal("100000"), Decimal("12"), 12, [(date(2025, 1, 15), Decimal("10000"))], as_of=date(2025, 1, 15)
        )
        assert result.principal_outstanding < Decimal("100000")

    def test_multiple_payments(self) -> None:
        payments = [(date(2025, 1, 15), Decimal("10000")), (date(2025, 2, 15), Decimal("10000"))]
        result = project_outstanding(Decimal("100000"), Decimal("12"), 12, payments, as_of=date(2025, 3, 1))
        assert result.principal_outstanding <= Decimal("90000")

    def test_excess_payment_does_not_go_negative(self) -> None:
        result = project_outstanding(
            Decimal("10000"), Decimal("12"), 6, [(date(2025, 1, 15), Decimal("50000"))], as_of=date(2025, 2, 1)
        )
        assert result.total_outstanding == Decimal("0")

    def test_accrued_interest_no_payments_zero_interest(self) -> None:
        result1 = project_outstanding(Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1))
        result2 = project_outstanding(Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 2, 1))
        assert result2.accrued_interest == result1.accrued_interest == Decimal("0")

    def test_days_overdue_no_payments(self) -> None:
        result = project_outstanding(Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 6, 1))
        assert result.days_overdue >= 0

    def test_days_overdue_with_recent_payment(self) -> None:
        result = project_outstanding(
            Decimal("100000"), Decimal("12"), 12, [(date(2025, 5, 30), Decimal("5000"))], as_of=date(2025, 6, 1)
        )
        assert result.days_overdue <= 5

    def test_empty_payments_future_as_of(self) -> None:
        result = project_outstanding(Decimal("50000"), Decimal("15"), 24, [], as_of=date(2025, 12, 31))
        assert result.total_outstanding == Decimal("50000")
        assert result.accrued_interest == Decimal("0")


class TestCalculateForeclosure:
    def test_no_penalty_zero_rate(self) -> None:
        result = calculate_foreclosure(
            Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1), penalty_rate=Decimal("0")
        )
        assert result.penalty == Decimal("0")

    def test_with_penalty_increases_total(self) -> None:
        result = calculate_foreclosure(
            Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1), penalty_rate=Decimal("3")
        )
        assert result.penalty > Decimal("0")

    def test_savings_with_schedule(self) -> None:
        sched = generate_schedule(Decimal("100000"), Decimal("12"), 12)
        result = calculate_foreclosure(
            Decimal("100000"),
            Decimal("12"),
            12,
            [(date(2025, 2, 1), sched.emi)],
            as_of=date(2025, 3, 1),
            penalty_rate=Decimal("0"),
            original_schedule=sched,
        )
        assert result.savings >= Decimal("0")

    def test_penalty_rate_impact(self) -> None:
        low = calculate_foreclosure(
            Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1), penalty_rate=Decimal("1")
        )
        high = calculate_foreclosure(
            Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1), penalty_rate=Decimal("5")
        )
        assert high.penalty > low.penalty

    def test_no_payments_no_schedule(self) -> None:
        result = calculate_foreclosure(Decimal("100000"), Decimal("12"), 12, [], as_of=date(2025, 1, 1))
        assert result.total_due == Decimal("100000")
        assert result.savings == Decimal("0")


class TestDataclassStructure:
    def test_emi_entry(self) -> None:
        e = EMIScheduleEntry(
            instalment_no=1,
            due_date=date(2025, 1, 1),
            emi_amount=Decimal("1000"),
            interest_component=Decimal("500"),
            principal_component=Decimal("500"),
            outstanding_principal=Decimal("9500"),
            total_interest_paid=Decimal("500"),
        )
        assert e.instalment_no == 1
        assert e.emi_amount == Decimal("1000")

    def test_schedule_defaults(self) -> None:
        s = AmortizationSchedule(
            principal=Decimal("0"), annual_interest_rate=Decimal("0"), tenure_months=0, emi=Decimal("0")
        )
        assert s.entries == []
        assert s.total_interest == Decimal("0")

    def test_outstanding_breakdown(self) -> None:
        ob = OutstandingBreakdown(
            total_outstanding=Decimal("50000"),
            principal_outstanding=Decimal("48000"),
            accrued_interest=Decimal("2000"),
            days_overdue=15,
        )
        assert ob.total_outstanding == Decimal("50000")
        assert ob.days_overdue == 15

    def test_foreclosure_quote(self) -> None:
        fq = ForeclosureQuote(
            outstanding_principal=Decimal("80000"),
            accrued_interest=Decimal("2000"),
            penalty=Decimal("0"),
            penalty_rate=Decimal("0"),
            total_due=Decimal("82000"),
            savings=Decimal("18000"),
            savings_percent=Decimal("18"),
        )
        assert fq.total_due == Decimal("82000")
        assert fq.savings == Decimal("18000")


class TestAmortizationBounds:
    def test_calculate_emi_rejects_huge_annual_rate(self) -> None:
        with pytest.raises(ValueError, match="exceeds 100%"):
            calculate_emi(Decimal("100000"), Decimal("200"), 12)

    def test_calculate_emi_rejects_century_tenure(self) -> None:
        with pytest.raises(ValueError, match="100 years"):
            calculate_emi(Decimal("100000"), Decimal("12"), 12 * 200)

    def test_calculate_foreclosure_rejects_negative_penalty(self) -> None:
        from datetime import date

        with pytest.raises(ValueError, match="penalty_rate"):
            calculate_foreclosure(
                principal=Decimal("100000"),
                annual_rate=Decimal("12"),
                tenure_months=12,
                payments_made=[],
                as_of=date(2025, 6, 1),
                penalty_rate=Decimal("-3"),
            )

    def test_calculate_foreclosure_rejects_huge_penalty(self) -> None:
        from datetime import date

        with pytest.raises(ValueError, match="penalty_rate"):
            calculate_foreclosure(
                principal=Decimal("100000"),
                annual_rate=Decimal("12"),
                tenure_months=12,
                payments_made=[],
                as_of=date(2025, 6, 1),
                penalty_rate=Decimal("150"),
            )
