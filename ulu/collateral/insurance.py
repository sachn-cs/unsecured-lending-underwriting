"""Collateral insurance policy tracking with expiry alerts.

Item 31 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum

from ulu.infra.logging import logger


class InsuranceStatus(enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CLAIMED = "claimed"


@dataclasses.dataclass
class InsurancePolicy:
    """Represents an insurance policy backing a collateral escrow."""

    policy_id: str
    escrow_id: str
    insurer: str
    coverage_amount: float
    premium: float
    start_date: datetime.date
    expiry_date: datetime.date
    status: InsuranceStatus = InsuranceStatus.ACTIVE


class InsuranceTrackingService:
    """Tracks collateral insurance policies and flags expiring coverage."""

    DEFAULT_ALERT_DAYS = 30

    def __init__(self) -> None:
        self._policies: dict[str, InsurancePolicy] = {}

    def register_policy(
        self,
        policy_id: str,
        escrow_id: str,
        insurer: str,
        coverage_amount: float,
        premium: float,
        start_date: datetime.date,
        expiry_date: datetime.date,
    ) -> InsurancePolicy:
        if coverage_amount <= 0:
            raise ValueError("coverage_amount must be positive")
        if premium < 0:
            raise ValueError("premium must be non-negative")
        if expiry_date <= start_date:
            raise ValueError("expiry_date must be after start_date")
        if policy_id in self._policies:
            raise ValueError(f"policy already exists: {policy_id}")
        policy = InsurancePolicy(
            policy_id=policy_id,
            escrow_id=escrow_id,
            insurer=insurer,
            coverage_amount=coverage_amount,
            premium=premium,
            start_date=start_date,
            expiry_date=expiry_date,
            status=InsuranceStatus.ACTIVE,
        )
        self._policies[policy_id] = policy
        logger.info("insurance_policy_registered", policy_id=policy_id, escrow_id=escrow_id)
        return policy

    def cancel_policy(self, policy_id: str) -> InsurancePolicy:
        policy = self._get(policy_id)
        policy.status = InsuranceStatus.CANCELLED
        logger.info("insurance_policy_cancelled", policy_id=policy_id)
        return policy

    def mark_claimed(self, policy_id: str) -> InsurancePolicy:
        policy = self._get(policy_id)
        if policy.status != InsuranceStatus.ACTIVE:
            raise ValueError("only active policies can be marked claimed")
        policy.status = InsuranceStatus.CLAIMED
        logger.info("insurance_policy_claimed", policy_id=policy_id)
        return policy

    def is_expired(self, policy: InsurancePolicy) -> bool:
        today = datetime.date.today()
        return policy.expiry_date < today

    def evaluate_status(self, policy_id: str) -> InsurancePolicy:
        """Evaluates and updates policy status based on expiry date."""
        policy = self._get(policy_id)
        if policy.status == InsuranceStatus.ACTIVE and self.is_expired(policy):
            policy.status = InsuranceStatus.EXPIRED
            logger.warning("insurance_policy_expired", policy_id=policy_id, escrow_id=policy.escrow_id)
        return policy

    def list_by_escrow(self, escrow_id: str) -> list[InsurancePolicy]:
        return [p for p in self._policies.values() if p.escrow_id == escrow_id]

    def list_expiring_soon(self, days: int | None = None) -> list[InsurancePolicy]:
        """Returns active policies expiring within the given number of days."""
        threshold = days or self.DEFAULT_ALERT_DAYS
        today = datetime.date.today()
        cutoff = today + datetime.timedelta(days=threshold)
        return [
            p for p in self._policies.values()
            if p.status == InsuranceStatus.ACTIVE and p.expiry_date <= cutoff
        ]

    def list_by_status(self, status: InsuranceStatus) -> list[InsurancePolicy]:
        return [p for p in self._policies.values() if p.status == status]

    def total_coverage(self, escrow_id: str) -> float:
        return sum(
            p.coverage_amount
            for p in self._policies.values()
            if p.escrow_id == escrow_id and p.status == InsuranceStatus.ACTIVE
        )

    def _get(self, policy_id: str) -> InsurancePolicy:
        policy = self._policies.get(policy_id)
        if policy is None:
            raise ValueError(f"policy not found: {policy_id}")
        return policy
