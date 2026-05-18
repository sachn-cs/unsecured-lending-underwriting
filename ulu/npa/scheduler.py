"""NPA status scheduler for automated aging transitions."""

from __future__ import annotations

from datetime import datetime, timezone

from ulu.npa.aging import NpaAgingTracker, NpaBucket


class NpaScheduler:
    """Schedules daily NPA status transitions based on aging rules."""

    def __init__(self, tracker: NpaAgingTracker | None = None) -> None:
        self.tracker = tracker if tracker is not None else NpaAgingTracker()

    def evaluate(self, days_overdue: int, last_evaluated_at: datetime | None = None) -> tuple[int, NpaBucket, bool]:
        """Evaluates NPA status using calendar anchoring to prevent double-aging."""
        now = datetime.now(timezone.utc)
        if last_evaluated_at is not None:
            delta_days = max(0, (now - last_evaluated_at).days)
        else:
            delta_days = 1
        new_days = days_overdue + delta_days
        bucket = self.tracker.bucket_for_days(new_days)
        dlg_trigger = self.tracker.is_dlg_trigger(new_days)
        return new_days, bucket, dlg_trigger
