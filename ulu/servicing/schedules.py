"""Loan amortization, bullet, and interest-only schedule generators."""

from __future__ import annotations

import enum

from ulu.domain.loans import Installment


class ScheduleType(enum.Enum):
    AMORTIZING = "amortizing"
    BULLET = "bullet"
    INTEREST_ONLY = "interest_only"


def generate_schedule(
    principal: float,
    term: int,
    annual_rate: float,
    schedule_type: ScheduleType,
    periods_per_year: int = 12,
) -> list[Installment]:
    """Generates a repayment schedule based on type.

    Args:
        principal: Loan principal amount (must be > 0).
        term: Number of periods (must be > 0).
        annual_rate: Annual interest rate as a decimal (must be >= 0).
        schedule_type: Type of repayment schedule.
        periods_per_year: Number of periods per year (default 12 for monthly).

    Returns:
        List of Installment objects representing the schedule.

    Raises:
        ValueError: If principal, term, or annual_rate are invalid.
    """
    if principal <= 0 or term <= 0 or annual_rate < 0:
        raise ValueError("principal, term must be positive; rate must be non-negative")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    periodic_rate = annual_rate / periods_per_year
    installments: list[Installment] = []

    if schedule_type == ScheduleType.BULLET:
        for seq in range(1, term + 1):
            if seq == term:
                installments.append(
                    Installment(seq, principal, principal * periodic_rate, principal + principal * periodic_rate)
                )
            else:
                installments.append(Installment(seq, 0.0, principal * periodic_rate, principal * periodic_rate))

    elif schedule_type == ScheduleType.INTEREST_ONLY:
        for seq in range(1, term + 1):
            installments.append(Installment(seq, 0.0, principal * periodic_rate, principal * periodic_rate))

    elif schedule_type == ScheduleType.AMORTIZING:
        if periodic_rate == 0:
            payment = principal / term
            for seq in range(1, term + 1):
                installments.append(Installment(seq, payment, 0.0, payment))
        else:
            payment = principal * (periodic_rate / (1.0 - (1.0 + periodic_rate) ** (-term)))
            remaining = principal
            for seq in range(1, term + 1):
                interest = remaining * periodic_rate
                principal_due = payment - interest
                if principal_due > remaining:
                    principal_due = remaining
                    payment = principal_due + interest
                remaining -= principal_due
                installments.append(Installment(seq, principal_due, interest, payment))

    return installments
