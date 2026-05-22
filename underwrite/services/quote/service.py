"""Loan pricing and quoting.  Stateless — reads state from the shared store."""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_negative, get_positive


class QuoteService(NanoService):
    """Computes loan quotes.  Pure function — no side effects on state."""

    def handle(self, event: Event) -> None:
        """Compute a loan quote and emit a QUOTE_CALCULATED event.

        This is a pure function with no side effects on persisted state.

        Args:
            event: The incoming event. Only ``quote`` events are processed.
        """
        if event.event_type != "quote":
            return
        p = event.payload
        principal: float = get_non_negative(p, "principal")
        term: float = get_positive(p, "term")
        dp: float = get_finite(p, "default_probability", 0.02)
        pr: float = get_finite(p, "protocol_rate", 0.10)
        mdr: float = get_finite(p, "max_delegation_rate", 0.05)
        borrower: str = p.get("borrower", "")

        protocol_premium: float = pr * principal * term
        break_even: float = 0.0
        if 0.0 < dp < 1.0 and term > 0:
            break_even = min(
                dp / ((1.0 - dp) * term),
                1e6,
            )

        self.emit(EventType.QUOTE_CALCULATED, {
            "borrower": borrower,
            "principal": principal,
            "term": term,
            "default_probability": dp,
            "protocol_rate": pr,
            "max_delegation_rate": mdr,
            "protocol_premium": protocol_premium,
            "break_even_rate": break_even,
            "total_interest": protocol_premium,
        },
                  correlation_id=event.correlation_id)
