"""Accounting queries and invariant assertion mixin."""

from __future__ import annotations

from ulu.errors import InvariantViolationError, ProtocolError


class AccountingMixin:
    """Methods for budget, credit limits, and state invariant checks."""

    def budget(self, user: str) -> float:
        """Returns current budget for a user."""
        self.require_user(user)
        if user in self.seeds:
            return self.base_budget[user] + self.earned[user]
        sponsor = self.parent[user]
        return self.delegation[(sponsor, user)] + self.earned[user]

    def outgoing_delegation(self, user: str) -> float:
        """Returns total outgoing delegation from a user."""
        self.require_user(user)
        return sum(self.delegation[(user, child)] for child in self.children[user])

    def credit_limit(self, user: str) -> float:
        """Returns paper-defined credit limit c_u."""
        return self.budget(user) - self.outgoing_delegation(user)

    def total_credit_limit(self) -> float:
        """Returns aggregate credit limit across all users."""
        return sum(self.credit_limit(user) for user in self.earned)

    def required_delegation(self, user: str) -> float:
        """Computes required delegation R_v recursively for non-seeds."""
        self.require_user(user)
        if user in self.seeds:
            raise ProtocolError("required delegation is defined only for non-seeds")
        child_requirement = sum(self.required_delegation(child) for child in self.children[user])
        return max(0.0, self.principal[user] + child_requirement - self.earned[user])

    def seed_delegation_utilization(self) -> float:
        """Returns U^D for current state."""
        denominator = sum(self.budget(seed) for seed in self.seeds)
        if denominator <= 0:
            raise InvariantViolationError("invalid state: non-positive seed budget total")

        numerator = 0.0
        for seed in self.seeds:
            for child in self.children[seed]:
                numerator += self.delegation[(seed, child)]

        utilization = numerator / denominator
        epsilon = self.config.epsilon
        if utilization < -epsilon or utilization > 1 + epsilon:
            raise InvariantViolationError("invalid state: utilization out of [0,1]")
        return min(max(utilization, 0.0), 1.0)

    def assert_invariants(self) -> None:
        """Raises if accounting or structure invariants are violated."""
        self.validate_structure()

        epsilon = self.config.epsilon
        for user in self.earned:
            if self.earned[user] < -epsilon:
                raise InvariantViolationError(f"negative earned credit for {user}")
            if self.principal[user] < -epsilon:
                raise InvariantViolationError(f"negative principal for {user}")
            if self.credit_limit(user) < -epsilon:
                raise InvariantViolationError(f"negative credit limit for {user}")

        for (sponsor, child), amount in self.delegation.items():
            if amount < -epsilon:
                raise InvariantViolationError(f"negative delegation on edge {sponsor}->{child}")
            if self.parent.get(child) != sponsor:
                raise InvariantViolationError(f"mismatched parent for edge {sponsor}->{child}")
            if child not in self.children.get(sponsor, []):
                raise InvariantViolationError(f"missing child link for edge {sponsor}->{child}")
