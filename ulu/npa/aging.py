"""NPA aging tracker and status bucket transitions per RBI norms."""

from __future__ import annotations

import enum


class NpaBucket(enum.Enum):
    STANDARD = "standard"
    NPA = "npa"
    SUBSTANDARD = "substandard"
    DOUBTFUL = "doubtful"
    LOSS = "loss"


class NpaAgingTracker:
    """Tracks days overdue and transitions through RBI NPA buckets.

    Per RBI Master Circular, classification thresholds are:
    - Standard:    0-90 days overdue
    - Substandard: 91-180 days overdue
    - Doubtful:    181-360 days overdue (subdivided into D1, D2, D3)
    - Loss:        >360 days overdue
    """

    def __init__(self, trigger_days: int = 120) -> None:
        self.trigger_days = trigger_days

    def bucket_for_days(self, days_overdue: int) -> NpaBucket:
        if days_overdue <= 0:
            return NpaBucket.STANDARD
        if days_overdue <= 90:
            return NpaBucket.STANDARD
        if days_overdue <= 180:
            return NpaBucket.SUBSTANDARD
        if days_overdue <= 360:
            return NpaBucket.DOUBTFUL
        return NpaBucket.LOSS

    def is_dlg_trigger(self, days_overdue: int) -> bool:
        return days_overdue >= self.trigger_days
