# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Loan pricing and quoting.  Stateless — reads state from the shared store."""

from __future__ import annotations

from underwrite.message import Message, Type
from underwrite.services.base import Core
from underwrite.validate import PayloadValidator


class Handler(Core):
    """Computes loan quotes.  Pure function — no side effects on state."""

    def handle(self, event: Message) -> None:
        """Compute a loan quote and emit a QUOTE_CALCULATED event.

        This is a pure function with no side effects on persisted state.

        Args:
            event: The incoming event. Only ``quote`` events are processed.
        """
        if event.event_type != Type.QUOTE:
            return
        p = event.payload
        principal: float = PayloadValidator().non_negative(p, "principal")
        term: float = PayloadValidator().positive(p, "term")
        dp: float = PayloadValidator().finite(p, "default_probability", 0.02)
        pr: float = PayloadValidator().finite(p, "protocol_rate", 0.10)
        mdr: float = PayloadValidator().finite(p, "max_delegation_rate", 0.05)
        borrower: str = p.get("borrower", "")

        # protocol_premium is the total protocol interest that would be
        # paid over the full term: per-period rate * principal * number
        # of periods. The field name is kept for backwards compatibility
        # with downstream services; the value is *total interest in
        # currency units*, not a per-period rate.  Use a more descriptive
        # alias in the emitted payload.
        total_interest: float = pr * principal * term
        break_even: float = 0.0
        if 0.0 < dp < 1.0 and term > 0:
            break_even = min(
                dp / ((1.0 - dp) * term),
                1e6,
            )

        self.emit(
            Type.QUOTE_CALCULATED,
            {
                "borrower": borrower,
                "principal": principal,
                "term": term,
                "default_probability": dp,
                "protocol_rate": pr,
                "max_delegation_rate": mdr,
                "protocol_premium": total_interest,
                "break_even_rate": break_even,
                "total_interest": total_interest,
            },
            correlation_id=event.correlation_id,
        )
