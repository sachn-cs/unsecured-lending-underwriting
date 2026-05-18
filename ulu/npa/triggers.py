"""Automated triggers for DLG invocation and regulatory actions."""

from __future__ import annotations

from ulu.domain.events import DlgInvocationEvent
from ulu.npa.aging import NpaAgingTracker


class DlgTriggerService:
    """Triggers DLG invocation when NPA reaches regulatory threshold."""

    def __init__(self, tracker: NpaAgingTracker | None = None) -> None:
        self.tracker = tracker if tracker is not None else NpaAgingTracker()

    def should_invoke(self, days_overdue: int, already_invoked: bool) -> bool:
        return self.tracker.is_dlg_trigger(days_overdue) and not already_invoked

    def invoke(self, loan_id: str, recovery_amount: float) -> DlgInvocationEvent:
        from datetime import datetime, timezone

        if recovery_amount < 0:
            raise ValueError("recovery_amount must be non-negative")
        return DlgInvocationEvent(
            event_type="dlg_invocation",
            payload={"loan_id": loan_id, "recovery_amount": recovery_amount},
            loan_id=loan_id,
            recovery_amount=recovery_amount,
            invoked_at=datetime.now(timezone.utc).isoformat(),
        )
