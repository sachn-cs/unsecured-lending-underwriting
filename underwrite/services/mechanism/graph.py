# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Pure domain model for the delegation-based underwriting graph.

Encapsulates all graph state (seeds, parent-child relationships,
delegation edges, budgets, loans) and the operations that transform
it. Has no dependencies on stores, event buses, or nano-service
infrastructure - making it testable in isolation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from underwrite.exceptions import InfeasibleOperationError, ProtocolError
from underwrite.logger import logger

ZERO: Decimal = Decimal("0")


def to_money(value: Any) -> Decimal:
    """Convert an int/float/str to an exact ``Decimal``.

    Floats are routed through ``str()`` first so ``0.1`` becomes
    ``Decimal("0.1")`` rather than the binary float expansion.

    Args:
        value: A numeric value or numeric string.

    Returns:
        The value as a Decimal.
    """
    return Decimal(str(value))


class DelegationGraph:
    """Encapsulates the delegation graph state and its operations.

    Thread-safety is the caller's responsibility (use state_lock in
    the owning service).
    """

    def __init__(self) -> None:
        self.seeds: set[str] = set()
        self.parent: dict[str, str] = {}
        self.children: dict[str, list[str]] = {}
        self.delegation: dict[tuple[str, str], Decimal] = {}
        self.base_budget: dict[str, Decimal] = {}
        self.earned: dict[str, Decimal] = {}
        self.principal: dict[str, Decimal] = {}
        self.loans: dict[str, list[dict[str, Any]]] = {}

    def require_user(self, user: str) -> None:
        """Raise ProtocolError if user is not a known participant.

        Args:
            user: The user to verify.

        Raises:
            ProtocolError: If the user is unknown.
        """
        if user not in self.earned:
            raise ProtocolError(f"unknown user: {user}")

    def credit_limit(self, user: str) -> Decimal:
        """Return the available credit limit for a user.

        Args:
            user: The user to query.

        Returns:
            Available credit limit (budget + earned - outgoing).
        """
        budget = self.base_budget.get(user, ZERO) + self.earned.get(user, ZERO)
        if user in self.parent:
            sponsor = self.parent[user]
            budget = self.delegation.get((sponsor, user), ZERO) + self.earned.get(user, ZERO)
        outgoing = sum(
            (self.delegation.get((user, child), ZERO) for child in self.children.get(user, [])),
            ZERO,
        )
        return budget - outgoing

    def total_credit_limit(self) -> Decimal:
        """Return the sum of all users' credit limits.

        Returns:
            Aggregate credit limit across all participants.
        """
        return sum((self.credit_limit(u) for u in self.earned), ZERO)

    def required_delegation(self, user: str, depth: int = 0) -> Decimal:
        """Minimum delegation a user must receive to remain solvent.

        Recursively accounts for downstream obligations.

        Args:
            user: The user to evaluate.
            depth: Current recursion depth (capped at 50).

        Returns:
            Required delegation amount.

        Raises:
            ProtocolError: If the delegation chain exceeds 50 depth.
        """
        if depth > 50:
            raise ProtocolError(f"delegation chain too deep for {user}")
        if user in self.seeds:
            return ZERO
        child_req = sum((self.required_delegation(c, depth + 1) for c in self.children.get(user, [])), ZERO)
        return max(
            ZERO,
            self.principal.get(user, ZERO) + child_req - self.earned.get(user, ZERO),
        )

    def path_to_seed(self, user: str) -> list[str]:
        """Return the delegation path from a user to a seed.

        Args:
            user: The starting user.

        Returns:
            List of user IDs from the seed to the user.

        Raises:
            ProtocolError: If user is unknown or a cycle is detected.
        """
        self.require_user(user)
        path: list[str] = [user]
        current: str = user
        seen: set[str] = {user}
        while current not in self.seeds:
            current = self.parent[current]
            if current in seen:
                raise ProtocolError(f"cycle detected for {user}")
            seen.add(current)
            path.append(current)
        path.reverse()
        return path

    def add_seed(self, user: str, budget: Decimal) -> None:
        """Register a new seed participant.

        Args:
            user: User identifier for the seed.
            budget: Base budget allocation.

        Raises:
            ProtocolError: If the user already exists.
        """
        if user in self.earned:
            raise ProtocolError(f"user already exists: {user}")
        self.seeds.add(user)
        self.base_budget[user] = budget
        self.earned[user] = ZERO
        self.principal[user] = ZERO
        self.children[user] = []

    def add_user(self, sponsor: str, user: str, amount: Decimal) -> None:
        """Add a new downstream participant sponsored by a seed/participant.

        Args:
            sponsor: The sponsoring participant.
            user: The new participant.
            amount: Delegation amount from sponsor to user.

        Raises:
            ProtocolError: If user already exists.
            InfeasibleOperationError: If sponsor lacks sufficient credit.
        """
        self.require_user(sponsor)
        if user in self.earned:
            raise ProtocolError(f"user already exists: {user}")
        if self.credit_limit(sponsor) < amount:
            raise InfeasibleOperationError("insufficient sponsor credit limit")
        self.parent[user] = sponsor
        self.children[user] = []
        self.children[sponsor].append(user)
        self.delegation[(sponsor, user)] = amount
        self.earned[user] = ZERO
        self.principal[user] = ZERO

    def repay(self, user: str, delta: Decimal) -> None:
        """Increase a user's earned amount by delta.

        Args:
            user: The user receiving credit.
            delta: Amount to add to earned.

        Raises:
            ProtocolError: If user is unknown.
        """
        self.require_user(user)
        self.earned[user] += delta

    def originate(
        self,
        borrower: str,
        principal: Decimal,
        term: Decimal,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> dict[str, Any]:
        """Issue a loan to a borrower and return the loan record.

        Args:
            borrower: The borrower.
            principal: Loan principal.
            term: Loan term.
            default_probability: Estimated default probability.
            protocol_rate: Protocol rate for premium calculation.
            max_delegation_rate: Maximum delegation rate.

        Returns:
            The loan record dict.

        Raises:
            InfeasibleOperationError: If principal exceeds credit limit.
        """
        self.require_user(borrower)
        if self.credit_limit(borrower) < principal:
            raise InfeasibleOperationError("principal exceeds credit limit")
        protocol_premium: Decimal = to_money(protocol_rate) * principal * term
        self.principal[borrower] = self.principal.get(borrower, ZERO) + principal
        loan: dict[str, Any] = {
            "borrower": borrower,
            "principal": principal,
            "term": term,
            "default_probability": default_probability,
            "protocol_rate": protocol_rate,
            "max_delegation_rate": max_delegation_rate,
            "protocol_premium": protocol_premium,
        }
        self.loans.setdefault(borrower, []).append(loan)
        return loan

    def default(self, borrower: str) -> None:
        """Process a default, propagating the loss up the delegation chain.

        Args:
            borrower: The defaulting borrower.

        Raises:
            ProtocolError: If user is unknown or loss cannot be absorbed.
            InfeasibleOperationError: If no outstanding principal.
        """
        self.require_user(borrower)
        borrower_principal: Decimal = self.principal.get(borrower, ZERO)
        if borrower_principal <= 0:
            raise InfeasibleOperationError("no outstanding principal")
        absorb: Decimal = min(self.earned.get(borrower, ZERO), borrower_principal)
        self.earned[borrower] = self.earned.get(borrower, ZERO) - absorb
        loss: Decimal = borrower_principal - absorb

        current: str = borrower
        while loss > 0 and current not in self.seeds:
            sponsor: str = self.parent[current]
            edge: tuple[str, str] = (sponsor, current)
            sponsor_absorb: Decimal = min(self.earned.get(sponsor, ZERO), loss)
            self.earned[sponsor] = self.earned.get(sponsor, ZERO) - sponsor_absorb
            loss -= sponsor_absorb
            if loss > 0:
                current_edge_amount: Decimal = self.delegation.get(edge, ZERO)
                if current_edge_amount < loss:
                    raise ProtocolError("insufficient delegation for default propagation")
                self.delegation[edge] = current_edge_amount - loss
            current = sponsor

        if loss > 0:
            if current not in self.seeds:
                raise ProtocolError("residual loss did not reach seed")
            seed_budget: Decimal = self.base_budget.get(current, ZERO)
            if seed_budget < loss:
                raise ProtocolError("seed base budget overdraft")
            self.base_budget[current] = seed_budget - loss

        self.principal[borrower] = ZERO
        self.loans.pop(borrower, None)

    def revoke(self, sponsor: str, child: str, new_amount: Decimal) -> None:
        """Change the delegation amount on a sponsor-child edge.

        Args:
            sponsor: The sponsoring participant.
            child: The downstream participant.
            new_amount: New delegation amount.

        Raises:
            ProtocolError: If users are unknown or edge does not exist.
            InfeasibleOperationError: If revocation would make subtree
                insolvent or if sponsor lacks credit to increase.
        """
        self.require_user(sponsor)
        self.require_user(child)
        if self.parent.get(child) != sponsor:
            raise ProtocolError("not the parent-child edge")
        needed: Decimal = self.required_delegation(child)
        if new_amount < needed:
            raise InfeasibleOperationError("revocation would make subtree insolvent")
        edge: tuple[str, str] = (sponsor, child)
        if edge not in self.delegation:
            raise ProtocolError("unknown delegation edge")
        old_amount: Decimal = self.delegation[edge]
        if new_amount > old_amount:
            delta: Decimal = new_amount - old_amount
            if self.credit_limit(sponsor) < delta:
                raise InfeasibleOperationError("insufficient credit limit to increase delegation")
        self.delegation[edge] = new_amount

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-ish copy of all mutable state for rollback.

        Returns:
            Dict of all graph state suitable for restore().
        """
        return {
            "seeds": set(self.seeds),
            "parent": dict(self.parent),
            "children": {k: list(v) for k, v in self.children.items()},
            "delegation": dict(self.delegation),
            "base_budget": dict(self.base_budget),
            "earned": dict(self.earned),
            "principal": dict(self.principal),
            "loans": {k: list(v) for k, v in self.loans.items()},
        }

    def restore(self, snap: dict[str, Any]) -> None:
        """Restore state from a snapshot (undo a mutation after persist failure).

        Args:
            snap: Snapshot previously returned by snapshot().
        """
        self.seeds = snap["seeds"]
        self.parent = snap["parent"]
        self.children = snap["children"]
        self.delegation = snap["delegation"]
        self.base_budget = snap["base_budget"]
        self.earned = snap["earned"]
        self.principal = snap["principal"]
        self.loans = snap["loans"]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for store persistence.

        Money fields are stored as strings so exact Decimal values
        survive the JSON round-trip.

        Returns:
            JSON-serializable dict.
        """
        return {
            "seeds": sorted(self.seeds),
            "parent": dict(self.parent),
            "children": {k: list(v) for k, v in self.children.items()},
            "delegation": {f"{s}->{c}": str(v) for (s, c), v in self.delegation.items()},
            "base_budget": {k: str(v) for k, v in self.base_budget.items()},
            "earned": {k: str(v) for k, v in self.earned.items()},
            "principal": {k: str(v) for k, v in self.principal.items()},
            "loans": [
                {
                    **loan,
                    "principal": str(loan["principal"]),
                    "term": str(loan["term"]),
                    "protocol_premium": str(loan["protocol_premium"]),
                }
                for borrower_loans in self.loans.values()
                for loan in borrower_loans
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegationGraph:
        """Deserialize from a dict previously produced by to_dict().

        Args:
            data: Dict representation of graph state.

        Returns:
            A new DelegationGraph instance.
        """
        g = cls()
        g.seeds = set(data.get("seeds", []))
        g.parent = dict(data.get("parent", {}))
        g.children = {k: list(v) for k, v in data.get("children", {}).items()}
        delegation_raw = data.get("delegation", {})
        g.delegation = {}
        for k, v in delegation_raw.items():
            s, c = k.split("->", 1)
            g.delegation[(s, c)] = to_money(v)
        g.base_budget = {k: to_money(v) for k, v in data.get("base_budget", {}).items()}
        g.earned = {k: to_money(v) for k, v in data.get("earned", {}).items()}
        g.principal = {k: to_money(v) for k, v in data.get("principal", {}).items()}
        g.loans = {}
        for raw_loan in data.get("loans", []):
            loan = dict(raw_loan)
            b = loan.get("borrower", "")
            if not b:
                logger.warning(
                    "Dropping loan with empty/missing borrower: {}",
                    loan.get("loan_id", "unknown"),
                )
                continue
            loan["principal"] = to_money(loan["principal"])
            loan["term"] = to_money(loan["term"])
            loan["protocol_premium"] = to_money(loan["protocol_premium"])
            g.loans.setdefault(b, []).append(loan)
        return g
