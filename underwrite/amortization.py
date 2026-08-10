"""EMI amortization engine for Indian lending.

Provides equal-monthly-installment (EMI) schedule generation, reducing
balance interest calculation (daily-reducing, monthly-rest), prepayment
and foreclosure computation, and outstanding balance projection.

Follows standard Indian banking conventions:
  - Interest: annual rate / 12 * outstanding principal (monthly rest)
  - EMI: P × r × (1+r)^n / ((1+r)^n - 1)
  - Prepayment penalty: only on fixed-rate loans (RBI guideline)
  - Foreclosure: full outstanding + accrued interest + penalty
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

DAYS_IN_YEAR = Decimal("365")
DAYS_IN_MONTH = Decimal("30.4167")


def _round_money(amount: Decimal, places: int = 2) -> Decimal:
    """Round to the given number of decimal places using HALF_UP."""
    return amount.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)


def _as_decimal(value: float | str | Decimal) -> Decimal:
    """Safely convert a value to Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value")
        return Decimal(str(value))
    return Decimal(value)


@dataclass(frozen=True, slots=True)
class EMIScheduleEntry:
    """A single EMI instalment in the amortization schedule."""

    instalment_no: int
    due_date: date
    emi_amount: Decimal
    interest_component: Decimal
    principal_component: Decimal
    outstanding_principal: Decimal
    total_interest_paid: Decimal


@dataclass(slots=True)
class AmortizationSchedule:
    """Complete amortization schedule for a loan."""

    principal: Decimal
    annual_interest_rate: Decimal
    tenure_months: int
    emi: Decimal
    entries: list[EMIScheduleEntry] = field(default_factory=list)
    total_interest: Decimal = Decimal("0")
    total_repayment: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal": float(self.principal),
            "annual_interest_rate": float(self.annual_interest_rate),
            "tenure_months": self.tenure_months,
            "emi": float(self.emi),
            "entries": [
                {
                    "instalment_no": e.instalment_no,
                    "due_date": e.due_date.isoformat(),
                    "emi_amount": float(e.emi_amount),
                    "interest_component": float(e.interest_component),
                    "principal_component": float(e.principal_component),
                    "outstanding_principal": float(e.outstanding_principal),
                    "total_interest_paid": float(e.total_interest_paid),
                }
                for e in self.entries
            ],
            "total_interest": float(self.total_interest),
            "total_repayment": float(self.total_repayment),
        }


def calculate_emi(principal: Decimal, annual_rate: Decimal, tenure_months: int) -> Decimal:
    """Calculate EMI using the standard formula.

    EMI = P × r × (1+r)^n / ((1+r)^n - 1)

    where:
      P = principal
      r = monthly interest rate (annual_rate / 12)
      n = tenure in months

    Raises:
        ValueError: If inputs are non-positive or non-finite.
    """
    if principal <= 0:
        raise ValueError("principal must be positive")
    if annual_rate <= 0:
        raise ValueError("annual_rate must be positive")
    if annual_rate > Decimal("100"):
        raise ValueError(f"annual_rate {annual_rate} exceeds 100% sanity bound")
    if tenure_months <= 0:
        raise ValueError("tenure_months must be positive")
    if tenure_months > 12 * 100:
        raise ValueError(f"tenure_months {tenure_months} exceeds 100 years; refusing to compute")
    monthly_rate = annual_rate / Decimal("1200")
    if monthly_rate == 0:
        return _round_money(principal / Decimal(tenure_months))
    factor = (Decimal("1") + monthly_rate) ** tenure_months
    emi = principal * monthly_rate * factor / (factor - Decimal("1"))
    return _round_money(emi)


def generate_schedule(
    principal: Decimal,
    annual_rate: Decimal,
    tenure_months: int,
    start_date: date | None = None,
    emi_override: Decimal | None = None,
) -> AmortizationSchedule:
    """Generate a full EMI amortization schedule.

    Uses monthly-reducing balance (standard Indian banking convention).
    Each instalment pays accrued interest first, then reduces principal.

    Args:
        principal: Loan principal amount.
        annual_rate: Annual interest rate in percent (e.g. 12.0 for 12%).
        tenure_months: Loan tenure in months.
        start_date: First EMI due date (defaults to today + 1 month).
        emi_override: Custom EMI amount (skips calculation).

    Returns:
        An AmortizationSchedule with all entries computed.

    Raises:
        ValueError: If inputs are invalid.
    """
    if start_date is None:
        today = date.today()
        month = today.month + 1
        year = today.year
        if month > 12:
            month = 1
            year += 1
        try:
            start_date = date(year, month, today.day)
        except ValueError:
            start_date = date(year, month, 1)

    p = principal
    r = annual_rate
    n = tenure_months
    if emi_override is not None:
        emi = _round_money(emi_override)
    else:
        emi = calculate_emi(p, r, n)
    monthly_rate = r / Decimal("1200")
    entries: list[EMIScheduleEntry] = []
    outstanding = p
    cumulative_interest = Decimal("0")

    due = start_date
    for i in range(1, n + 1):
        interest_due = _round_money(outstanding * monthly_rate)
        principal_due = emi - interest_due
        if principal_due < 0:
            principal_due = Decimal("0")
        if principal_due > outstanding:
            principal_due = outstanding
        outstanding -= principal_due
        if outstanding < Decimal("0.005"):
            outstanding = Decimal("0")
        cumulative_interest += interest_due
        entries.append(
            EMIScheduleEntry(
                instalment_no=i,
                due_date=due,
                emi_amount=_round_money(emi),
                interest_component=_round_money(interest_due),
                principal_component=_round_money(principal_due),
                outstanding_principal=_round_money(outstanding),
                total_interest_paid=_round_money(cumulative_interest),
            )
        )
        m = due.month + 1
        y = due.year
        if m > 12:
            m = 1
            y += 1
        try:
            due = date(y, m, start_date.day)
        except ValueError:
            due = date(y, m, min(start_date.day, 28))

    total_interest_val = _round_money(cumulative_interest)
    total_repayment_val = _round_money(p + cumulative_interest)
    return AmortizationSchedule(
        principal=p,
        annual_interest_rate=r,
        tenure_months=n,
        emi=_round_money(emi),
        entries=entries,
        total_interest=total_interest_val,
        total_repayment=total_repayment_val,
    )


@dataclass(frozen=True, slots=True)
class OutstandingBreakdown:
    """Breakdown of outstanding at a point in time."""

    total_outstanding: Decimal
    principal_outstanding: Decimal
    accrued_interest: Decimal
    days_overdue: int


def project_outstanding(
    principal: Decimal,
    annual_rate: Decimal,
    tenure_months: int,
    payments_made: list[tuple[date, Decimal]],
    as_of: date | None = None,
) -> OutstandingBreakdown:
    """Project outstanding principal and accrued interest given payments.

    Uses daily-reducing balance for accrued interest calculation.
    Each payment is applied first to accrued interest, then to principal.

    Args:
        principal: Original loan principal.
        annual_rate: Annual interest rate in percent.
        tenure_months: Original loan tenure.
        payments_made: List of (payment_date, amount) payments.
        as_of: Date to project outstanding as of (defaults to today).

    Returns:
        OutstandingBreakdown with current state.
    """
    if as_of is None:
        as_of = date.today()
    daily_rate = annual_rate / Decimal("36500")
    outstanding = principal
    last_date = date.today()
    if tenure_months > 0:
        month = last_date.month + tenure_months
        year = last_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        try:
            last_date = date(year, month, min(last_date.day, 28))
        except ValueError:
            last_date = date(year, month, 1)

    payments = sorted(
        (p for p in payments_made if p[1] >= 0),
        key=lambda x: x[0],
    )
    accrued = Decimal("0")

    prev_date = min(payments[0][0] if payments else as_of, as_of)
    for pay_date, amount in payments:
        if pay_date < prev_date:
            continue
        days = (pay_date - prev_date).days
        if days > 0:
            accrued += _round_money(outstanding * daily_rate * Decimal(days))
        if amount >= accrued:
            principal_part = amount - accrued
            outstanding -= principal_part
            if outstanding < Decimal("0.01"):
                outstanding = Decimal("0")
            accrued = Decimal("0")
        else:
            accrued -= amount
            if accrued < Decimal("0.01"):
                accrued = Decimal("0")
        prev_date = pay_date

    days_since = (as_of - prev_date).days
    if days_since > 0:
        accrued += _round_money(outstanding * daily_rate * Decimal(days_since))

    if outstanding < Decimal("0.01"):
        outstanding = Decimal("0")
    if accrued < Decimal("0.01"):
        accrued = Decimal("0")

    total = _round_money(outstanding + accrued)
    days_overdue = max(0, (as_of - prev_date).days) if payments else 0

    return OutstandingBreakdown(
        total_outstanding=total,
        principal_outstanding=_round_money(outstanding),
        accrued_interest=_round_money(accrued),
        days_overdue=days_overdue,
    )


@dataclass(frozen=True, slots=True)
class ForeclosureQuote:
    """Quote for full prepayment (foreclosure) of a loan."""

    outstanding_principal: Decimal
    accrued_interest: Decimal
    penalty: Decimal
    penalty_rate: Decimal
    total_due: Decimal
    savings: Decimal
    savings_percent: Decimal


def calculate_foreclosure(
    principal: Decimal,
    annual_rate: Decimal,
    tenure_months: int,
    payments_made: list[tuple[date, Decimal]],
    as_of: date | None = None,
    penalty_rate: Decimal = Decimal("0"),
    original_schedule: AmortizationSchedule | None = None,
) -> ForeclosureQuote:
    """Calculate full prepayment (foreclosure) amount.

    Per RBI guidelines, foreclosure/prepayment penalty is NOT allowed
    on floating-rate loans extended to individuals for non-business
    purposes. For fixed-rate loans, max 3% penalty applies.

    Args:
        principal: Original loan principal.
        annual_rate: Annual interest rate.
        tenure_months: Original loan tenure.
        payments_made: Payments made so far.
        as_of: Date to calculate as of.
        penalty_rate: Prepayment penalty rate in percent (0 for floating).
        original_schedule: Original amortization schedule (for savings calc).

    Returns:
        ForeclosureQuote with breakdown.
    """
    outstanding = project_outstanding(principal, annual_rate, tenure_months, payments_made, as_of)
    if penalty_rate < Decimal("0") or penalty_rate > Decimal("100"):
        raise ValueError(f"penalty_rate must be between 0 and 100 (got {penalty_rate})")
    if outstanding.total_outstanding < Decimal("0"):
        raise ValueError("computed outstanding is negative; check inputs")
    penalty = _round_money(outstanding.total_outstanding * penalty_rate / Decimal("100"))
    total_due = _round_money(outstanding.total_outstanding + penalty)

    interest_already = outstanding.accrued_interest
    total_schedule_interest = sum(
        e.interest_component for e in (original_schedule.entries if original_schedule else [])
    )
    if total_schedule_interest > 0:
        interest_remaining = total_schedule_interest - interest_already
        if interest_remaining < Decimal("0"):
            interest_remaining = Decimal("0")
    else:
        interest_remaining = Decimal("0")
    savings = _round_money(interest_remaining)
    savings_pct = Decimal("0")
    if total_schedule_interest > 0:
        savings_pct = _round_money(savings / total_schedule_interest * Decimal("100"))

    return ForeclosureQuote(
        outstanding_principal=outstanding.principal_outstanding,
        accrued_interest=outstanding.accrued_interest,
        penalty=penalty,
        penalty_rate=penalty_rate,
        total_due=total_due,
        savings=savings,
        savings_percent=savings_pct,
    )
