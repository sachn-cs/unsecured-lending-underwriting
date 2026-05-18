"""Core delegated-underwriting mechanism and accounting state transitions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ulu.audit import AppendOnlyLedger
from ulu.core.graph import GraphMixin
from ulu.core.invariants import AccountingMixin
from ulu.core.models import LoanQuote, ProtocolConfig, ProtocolState
from ulu.core.pricing import PricingMixin
from ulu.core.serialization import SerializationMixin
from ulu.errors import InfeasibleOperationError, InvariantViolationError, ProtocolError
from ulu.infra.logging import logger

__all__ = [
    "DelegatedUnderwriting",
    "LoanQuote",
    "ProtocolConfig",
    "ProtocolState",
]


class DelegatedUnderwriting(GraphMixin, PricingMixin, AccountingMixin, SerializationMixin):
    """Implements paper-defined mechanism transitions and pricing."""

    def __init__(
        self,
        config: ProtocolConfig | None = None,
        ledger: AppendOnlyLedger | None = None,
    ) -> None:
        """Initializes an empty protocol state."""
        self.config = config or ProtocolConfig()
        self.ledger = ledger

        self.seeds: set[str] = set()
        self.parent: dict[str, str] = {}
        self.children: dict[str, list[str]] = {}
        self.delegation: dict[tuple[str, str], float] = {}
        self.base_budget: dict[str, float] = {}
        self.earned: dict[str, float] = {}
        self.principal: dict[str, float] = {}

    def record_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.ledger is not None:
            self.ledger.append(event_type=event_type, payload=dict(payload))

    def add_seed(self, user: str, base_budget: float) -> None:
        """Adds a new seed account with positive base budget."""
        if user in self.earned:
            raise ProtocolError(f"user already exists: {user}")
        if base_budget <= 0:
            raise ProtocolError("seed base budget must be > 0")

        self.seeds.add(user)
        self.base_budget[user] = float(base_budget)
        self.earned[user] = 0.0
        self.principal[user] = 0.0
        self.children[user] = []

        logger.info("add_seed", user=user, base_budget=float(base_budget))
        self.record_event("add_seed", {"user": user, "base_budget": float(base_budget)})

    def add_user(self, sponsor: str, user: str, delegation_amount: float) -> None:
        """Adds a non-seed user sponsored with delegated capacity."""
        self.require_user(sponsor)
        if user in self.earned:
            raise ProtocolError(f"user already exists: {user}")
        if delegation_amount <= 0:
            raise ProtocolError("delegation must be > 0")
        if self.credit_limit(sponsor) < delegation_amount:
            raise InfeasibleOperationError("insufficient sponsor credit limit for delegation")

        self.parent[user] = sponsor
        self.children[user] = []
        self.children[sponsor].append(user)
        self.delegation[(sponsor, user)] = float(delegation_amount)
        self.earned[user] = 0.0
        self.principal[user] = 0.0

        logger.info(
            "add_user",
            sponsor=sponsor,
            user=user,
            delegation_amount=float(delegation_amount),
        )
        self.record_event(
            "add_user",
            {
                "sponsor": sponsor,
                "user": user,
                "delegation_amount": float(delegation_amount),
            },
        )

    def revoke(self, sponsor: str, child: str, new_delegation: float) -> None:
        """Sets edge delegation amount if revocation remains solvent."""
        self.require_user(sponsor)
        self.require_user(child)
        edge = (sponsor, child)
        if edge not in self.delegation:
            raise ProtocolError("unknown delegation edge")
        if self.parent.get(child) != sponsor:
            raise ProtocolError("not the parent-child edge")
        if new_delegation < 0:
            raise ProtocolError("new delegation must be >= 0")

        needed = self.required_delegation(child)
        if new_delegation < needed:
            raise InfeasibleOperationError("revocation would make subtree insolvent")

        old_delegation = self.delegation[edge]
        if new_delegation > old_delegation:
            delta = new_delegation - old_delegation
            if self.credit_limit(sponsor) < delta:
                raise InfeasibleOperationError("insufficient credit limit to increase delegation")

        self.delegation[edge] = float(new_delegation)
        logger.info(
            "revoke",
            sponsor=sponsor,
            child=child,
            old_delegation=float(old_delegation),
            new_delegation=float(new_delegation),
        )
        self.record_event(
            "revoke",
            {
                "sponsor": sponsor,
                "child": child,
                "old_delegation": float(old_delegation),
                "new_delegation": float(new_delegation),
            },
        )

    def repay(self, user: str, delta_earned: float) -> None:
        """Applies earned-credit increment from repayment."""
        self.require_user(user)
        if delta_earned < 0:
            raise ProtocolError("delta earned must be >= 0")
        self.earned[user] += float(delta_earned)

        logger.info("repay", user=user, delta_earned=float(delta_earned))
        self.record_event("repay", {"user": user, "delta_earned": float(delta_earned)})

    def originate_loan(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> LoanQuote:
        """Quotes and originates a loan by setting borrower principal."""
        quote = self.quote_loan(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            max_delegation_rate=max_delegation_rate,
        )
        self.principal[borrower] = principal

        logger.info(
            "originate_loan",
            borrower=borrower,
            principal=float(principal),
            term=float(term),
        )
        self.record_event(
            "originate_loan",
            {"borrower": borrower, "principal": float(principal), "term": float(term)},
        )
        return quote

    def default(self, borrower: str) -> None:
        """Applies default loss propagation on borrower sponsor path."""
        self.require_user(borrower)
        borrower_principal = self.principal[borrower]
        if borrower_principal <= 0:
            raise InfeasibleOperationError("borrower has no outstanding principal")

        absorb_borrower = min(self.earned[borrower], borrower_principal)
        self.earned[borrower] -= absorb_borrower
        loss = borrower_principal - absorb_borrower

        current = borrower
        while loss > 0 and current not in self.seeds:
            sponsor = self.parent[current]
            edge = (sponsor, current)
            absorb_sponsor = min(self.earned[sponsor], loss)
            self.earned[sponsor] -= absorb_sponsor
            loss -= absorb_sponsor
            if loss > 0:
                if self.delegation[edge] < loss:
                    raise InvariantViolationError("invalid state: insufficient delegation for default propagation")
                self.delegation[edge] -= loss
            current = sponsor

        if loss > 0:
            if current not in self.seeds:
                raise InvariantViolationError("invalid state: residual loss did not reach seed")
            seed = current
            if self.base_budget[seed] < loss:
                raise InvariantViolationError("invalid state: seed base budget overdraft")
            self.base_budget[seed] -= loss

        self.principal[borrower] = 0.0
        logger.info("default", borrower=borrower, principal=float(borrower_principal))
        self.record_event("default", {"borrower": borrower, "principal": float(borrower_principal)})
