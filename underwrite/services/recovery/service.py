"""Recovery workflows — post-default recovery orchestration."""

from __future__ import annotations

from datetime import datetime, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty


class RecoveryService(NanoService):
    """Orchestrates recovery actions after a default event."""

    def handle(self, event: Event) -> None:
        if event.event_type != EventType.DEFAULT_OCCURRED:
            return
        borrower: str = get_non_empty(event.payload, "borrower")
        principal: float = get_finite(event.payload, "principal")
        self.emit(EventType.RECOVERY_STARTED, {
            "borrower": borrower,
            "principal": principal,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
                  correlation_id=event.correlation_id)
        recovery_amount: float = principal * 0.3
        self.emit(EventType.RECOVERY_COMPLETED, {
            "borrower": borrower,
            "recovered": recovery_amount,
            "outstanding": principal - recovery_amount,
        },
                  correlation_id=event.correlation_id)
