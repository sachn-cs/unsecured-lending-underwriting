"""Underwriter — evaluates loan applications and decides approval.

Listens for ``underwrite.request`` events, evaluates borrower risk
metrics, and emits ``underwriter.approved`` or ``underwriter.rejected``.
"""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty

MAX_DEFAULT_PROBABILITY: float = 0.25
MIN_CREDIT_LIMIT: float = 1000.0


class UnderwriterService(NanoService):
    """Evaluates loan applications against risk policies."""

    def handle(self, event: Event) -> None:
        if event.event_type != "underwrite.request":
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")
        dp: float = get_finite(p, "default_probability", 0.0)

        reasons: list[str] = []
        if principal <= 0:
            reasons.append("principal_must_be_positive")
        if dp > MAX_DEFAULT_PROBABILITY:
            reasons.append(
                f"default_probability_{dp:.2f}_exceeds_{MAX_DEFAULT_PROBABILITY}"
            )

        if reasons:
            self.emit(EventType.UNDERWRITER_REJECTED, {
                "borrower": borrower,
                "principal": principal,
                "reasons": reasons,
            },
                      correlation_id=event.correlation_id)
        else:
            self.emit(EventType.UNDERWRITER_APPROVED, {
                "borrower": borrower,
                "principal": principal,
            },
                      correlation_id=event.correlation_id)
