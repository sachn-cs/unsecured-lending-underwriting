"""Domain event types for event sourcing and audit trails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SeedAddedEvent(DomainEvent):
    """Emitted when a new seed is registered."""

    user_id: str
    base_budget: float


@dataclass(frozen=True)
class UserAddedEvent(DomainEvent):
    """Emitted when a sponsored user is onboarded."""

    sponsor_id: str
    user_id: str
    delegation_amount: float


@dataclass(frozen=True)
class LoanOriginatedEvent(DomainEvent):
    """Emitted when a loan is originated."""

    loan_id: str
    borrower_id: str
    principal: float
    term: float


@dataclass(frozen=True)
class RepaymentEvent(DomainEvent):
    """Emitted when a repayment is processed."""

    loan_id: str
    amount: float
    delta_earned: float


@dataclass(frozen=True)
class DefaultEvent(DomainEvent):
    """Emitted when a borrower defaults."""

    loan_id: str
    borrower_id: str
    default_amount: float
    logical_loss: float
    physical_recovery: float


@dataclass(frozen=True)
class CollateralBreachEvent(DomainEvent):
    """Emitted when collateral ratio falls below threshold."""

    owner_id: str
    current_ratio: float
    required_ratio: float


@dataclass(frozen=True)
class DlgInvocationEvent(DomainEvent):
    """Emitted when DLG is invoked on an NPA."""

    loan_id: str
    recovery_amount: float
    invoked_at: str


@dataclass(frozen=True)
class RecoveryEvent(DomainEvent):
    """Emitted when a recovery workflow is initiated."""

    loan_id: str
    borrower_id: str
    recovery_type: str
    recovered_amount: float
    default_amount: float


@dataclass(frozen=True)
class KycStatusChangeEvent(DomainEvent):
    """Emitted when KYC status changes."""

    user_id: str
    old_status: str
    new_status: str
    reason: str


@dataclass(frozen=True)
class AmlStatusChangeEvent(DomainEvent):
    """Emitted when AML status changes."""

    user_id: str
    old_status: str
    new_status: str
    reason: str
