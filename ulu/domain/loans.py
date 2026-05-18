"""Loan domain models, status enums, and value objects."""

from __future__ import annotations

import enum


class LoanStatus(enum.Enum):
    ORIGINATED = "originated"
    ACTIVE = "active"
    OVERDUE = "overdue"
    DEFAULTED = "defaulted"
    RECOVERED = "recovered"
    WRITTEN_OFF = "written_off"


class RepaymentType(enum.Enum):
    SCHEDULED = "scheduled"
    PREPAYMENT = "prepayment"
    PARTIAL = "partial"


class RecoveryType(enum.Enum):
    WORKOUT = "workout"
    RESTRUCTURE = "restructure"
    LIQUIDATION = "liquidation"
    WRITE_OFF = "write_off"


class Installment:
    """Represents a single due payment in a loan schedule."""

    def __init__(
        self,
        sequence: int,
        principal_due: float,
        interest_due: float,
        total_due: float,
    ) -> None:
        self.sequence = sequence
        self.principal_due = principal_due
        self.interest_due = interest_due
        self.total_due = total_due

    def __repr__(self) -> str:
        return (
            f"Installment(seq={self.sequence}, principal={self.principal_due:.2f}, "
            f"interest={self.interest_due:.2f}, total={self.total_due:.2f})"
        )
