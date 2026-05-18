"""Loan pricing and quote generation mixin."""

from __future__ import annotations

from ulu.core.models import LoanQuote
from ulu.errors import InfeasibleOperationError, ProtocolError


class PricingMixin:
    """Methods for loan quoting and rate calculations."""

    def protocol_break_even_rate(self, default_probability: float, term: float) -> float:
        """Returns exact break-even protocol rate from theorem condition."""
        if not (0.0 < default_probability < 1.0):
            raise ProtocolError("default probability must be in (0,1)")
        if term <= 0:
            raise ProtocolError("term must be > 0")
        _EPS = 1e-12
        _MAX_RATE = 1e6
        clamped_dp = max(default_probability, _EPS)
        clamped_term = max(term, _EPS)
        rate = clamped_dp / ((1 - clamped_dp) * clamped_term)
        return min(rate, _MAX_RATE)

    def validate_quote_inputs(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> None:
        self.require_user(borrower)
        if self.principal[borrower] != 0:
            raise InfeasibleOperationError("borrower already has outstanding principal")
        if self.credit_limit(borrower) < principal:
            raise InfeasibleOperationError("borrower principal exceeds credit limit")
        if term <= 0 or principal <= 0:
            raise ProtocolError("principal and term must be > 0")
        if protocol_rate < 0 or max_delegation_rate < 0:
            raise ProtocolError("rates must be >= 0")
        if not (0.0 < default_probability < 1.0):
            raise ProtocolError("default probability must be in (0,1)")

    def quote_loan(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> LoanQuote:
        """Produces a snapshot loan quote without mutating principal."""
        self.validate_quote_inputs(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            max_delegation_rate=max_delegation_rate,
        )

        protocol_premium = protocol_rate * principal * term
        utilization = self.seed_delegation_utilization()
        delegation_rate = max_delegation_rate * (1 - utilization)
        locked = self.locked_delegation(borrower, principal)

        path = self.path_seed_to(borrower)
        payouts: dict[str, float] = {}
        for index in range(len(path) - 1):
            sponsor = path[index]
            edge = (path[index], path[index + 1])
            payouts[sponsor] = delegation_rate * locked[edge] * term

        delegation_premium = sum(payouts.values())
        return LoanQuote(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            protocol_premium=protocol_premium,
            delegation_utilization=utilization,
            delegation_rate=delegation_rate,
            locked_by_edge=locked,
            delegation_payouts=payouts,
            delegation_premium=delegation_premium,
            total_interest=protocol_premium + delegation_premium,
        )

