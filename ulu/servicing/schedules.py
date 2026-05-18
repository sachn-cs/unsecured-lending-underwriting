"""Loan amortization, bullet, and interest-only schedule generators."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ulu.domain.loans import Installment


class ScheduleType(enum.Enum):
    AMORTIZING = "amortizing"
    BULLET = "bullet"
    INTEREST_ONLY = "interest_only"


@dataclass(frozen=True)
class ScheduleVersion:
    """Versioned repayment schedule with change metadata."""

    version: int
    created_at: str
    change_reason: str
    principal: float
    term: int
    annual_rate: float
    schedule_type: ScheduleType
    installments: list[Installment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


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


def generate_schedule_decimal(
    principal: Decimal,
    term: int,
    annual_rate: Decimal,
    schedule_type: ScheduleType,
    periods_per_year: int = 12,
) -> list[Installment]:
    """Generates a repayment schedule using Decimal for monetary precision.

    Args:
        principal: Loan principal amount (must be > 0).
        term: Number of periods (must be > 0).
        annual_rate: Annual interest rate as a Decimal (must be >= 0).
        schedule_type: Type of repayment schedule.
        periods_per_year: Number of periods per year (default 12 for monthly).

    Returns:
        List of Installment objects representing the schedule.
    """
    if principal <= 0 or term <= 0 or annual_rate < 0:
        raise ValueError("principal, term must be positive; rate must be non-negative")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    periodic_rate = annual_rate / Decimal(periods_per_year)
    installments: list[Installment] = []
    p_float = float(principal)

    if schedule_type == ScheduleType.BULLET:
        for seq in range(1, term + 1):
            interest = float(principal * periodic_rate)
            if seq == term:
                installments.append(
                    Installment(seq, p_float, interest, p_float + interest)
                )
            else:
                installments.append(Installment(seq, 0.0, interest, interest))

    elif schedule_type == ScheduleType.INTEREST_ONLY:
        interest = float(principal * periodic_rate)
        for seq in range(1, term + 1):
            installments.append(Installment(seq, 0.0, interest, interest))

    elif schedule_type == ScheduleType.AMORTIZING:
        if periodic_rate == 0:
            payment = principal / Decimal(term)
            pmt_float = float(payment)
            for seq in range(1, term + 1):
                installments.append(Installment(seq, pmt_float, 0.0, pmt_float))
        else:
            payment = principal * (periodic_rate / (Decimal(1) - (Decimal(1) + periodic_rate) ** (-term)))
            remaining = principal
            for seq in range(1, term + 1):
                interest = remaining * periodic_rate
                principal_due = payment - interest
                if principal_due > remaining:
                    principal_due = remaining
                    payment = principal_due + interest
                remaining -= principal_due
                installments.append(
                    Installment(
                        seq,
                        float(principal_due),
                        float(interest),
                        float(payment),
                    )
                )

    return installments


def versioned_schedule(
    principal: float,
    term: int,
    annual_rate: float,
    schedule_type: ScheduleType,
    version: int = 1,
    change_reason: str = "origination",
    created_at: str = "",
    periods_per_year: int = 12,
    metadata: dict[str, Any] | None = None,
) -> ScheduleVersion:
    """Generates a versioned repayment schedule."""
    installments = generate_schedule(
        principal=principal,
        term=term,
        annual_rate=annual_rate,
        schedule_type=schedule_type,
        periods_per_year=periods_per_year,
    )
    return ScheduleVersion(
        version=version,
        created_at=created_at,
        change_reason=change_reason,
        principal=principal,
        term=term,
        annual_rate=annual_rate,
        schedule_type=schedule_type,
        installments=installments,
        metadata=metadata or {},
    )


class ScheduleVersionManager:
    """Manages version history for a borrower's repayment schedules."""

    def __init__(self) -> None:
        self._versions: list[ScheduleVersion] = []

    def add_version(self, version: ScheduleVersion) -> None:
        """Appends a new schedule version."""
        self._versions.append(version)

    def latest(self) -> ScheduleVersion | None:
        """Returns the most recent schedule version."""
        if not self._versions:
            return None
        return self._versions[-1]

    def history(self) -> list[ScheduleVersion]:
        """Returns all versions in chronological order."""
        return list(self._versions)

    def restructure(
        self,
        principal: float,
        term: int,
        annual_rate: float,
        schedule_type: ScheduleType,
        reason: str,
        created_at: str = "",
        periods_per_year: int = 12,
    ) -> ScheduleVersion:
        """Creates a new schedule version with incremented version number."""
        next_version = len(self._versions) + 1
        new_schedule = versioned_schedule(
            principal=principal,
            term=term,
            annual_rate=annual_rate,
            schedule_type=schedule_type,
            version=next_version,
            change_reason=reason,
            created_at=created_at,
            periods_per_year=periods_per_year,
            metadata={"previous_version": next_version - 1},
        )
        self.add_version(new_schedule)
        return new_schedule
