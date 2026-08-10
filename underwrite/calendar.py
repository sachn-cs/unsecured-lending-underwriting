"""Indian holiday calendar for loan due-date adjustments.

Provides gazetted holiday lists and utility functions to shift due
dates to the next working day when they fall on a holiday or weekend.

Follows RBI's list of bank holidays for clearing/settlement,
modified for calendar year 2025-2030.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from importlib import resources

from underwrite.logger import logger

_HOLIDAYS_DATA: dict[str, list[dict[str, int]]] | None = None


def _load_holidays() -> dict[str, list[dict[str, int]]]:
    """Load holiday data from the bundled JSON table. Cached after first load.

    The JSON lives at ``underwrite/data/holidays.json`` and is shipped as
    package data so it survives an editable install and the runtime
    ``data/`` directory remains free for per-deployment state.
    """
    global _HOLIDAYS_DATA
    if _HOLIDAYS_DATA is None:
        payload = resources.files("underwrite.data").joinpath("holidays.json").read_text(encoding="utf-8")
        _HOLIDAYS_DATA = json.loads(payload)
    return _HOLIDAYS_DATA


def fixed_holidays(start_year: int = 2025, end_year: int = 2027) -> set[tuple[int, int, int]]:
    """Return set of (year, month, day) tuples for fixed-date holidays."""
    data = _load_holidays()
    holidays: set[tuple[int, int, int]] = set()
    for year in range(start_year, end_year + 1):
        for entry in data["fixed"]:
            holidays.add((year, entry["month"], entry["day"]))
    return holidays


def moveable_holidays(start_year: int = 2025, end_year: int = 2030) -> set[tuple[int, int, int]]:
    """Return set of (year, month, day) for moveable holidays.

    These are approximate dates and should be updated annually based
    on official RBI circulars. Coverage extends through 2030; queries
    outside the configured range fall back to fixed holidays and
    weekend rules only (with a logged warning at module import time).
    """
    data = _load_holidays()
    moveable: dict[str, list[dict[str, int]]] = data["moveable"]  # type: ignore[assignment]
    holidays: set[tuple[int, int, int]] = set()
    for year in range(start_year, end_year + 1):
        key = str(year)
        if key in moveable:
            for entry in moveable.get(key, []):
                holidays.add((year, entry["month"], entry["day"]))
    return holidays


HOLIDAY_CACHE: dict[int, set[date]] = {}
HOLIDAY_GENERATED: set[int] = set()


def __ensure_holidays(year: int) -> None:
    if year in HOLIDAY_GENERATED:
        return
    holidays: set[date] = set()
    fixed = fixed_holidays(year, year)
    moveable = moveable_holidays(year, year)
    for y, m, d in fixed | moveable:
        try:
            holidays.add(date(y, m, d))
        except ValueError:
            logger.warning("invalid holiday date: {}-{}-{}", y, m, d)
    sundays_and_sats: set[date] = set()
    for month in range(1, 13):
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            dt = date(year, month, day)
            if dt.weekday() == 6:
                sundays_and_sats.add(dt)
            if dt.weekday() == 5 and (is_second_saturday(dt) or is_fourth_saturday(dt)):
                sundays_and_sats.add(dt)
    HOLIDAY_CACHE[year] = holidays | sundays_and_sats
    HOLIDAY_GENERATED.add(year)


def is_holiday(dt: date) -> bool:
    """Check if a given date is a holiday (gazetted + Sunday).

    Args:
        dt: The date to check.

    Returns:
        True if the date is a holiday.
    """
    __ensure_holidays(dt.year)
    return dt in HOLIDAY_CACHE.get(dt.year, set())


def is_business_day(dt: date) -> bool:
    """Check if a given date is a business day (not holiday, not Sunday).

    Args:
        dt: The date to check.

    Returns:
        True if the date is a business day.
    """
    return not is_holiday(dt)


def next_business_day(dt: date) -> date:
    """Return the next business day from the given date.

    If *dt* is already a business day, returns *dt*.
    Otherwise, advances until a business day is found.

    Args:
        dt: Starting date.

    Returns:
        The next business day on or after *dt*.
    """
    while is_holiday(dt):
        dt += timedelta(days=1)
    return dt


def previous_business_day(dt: date) -> date:
    """Return the previous business day before the given date.

    If *dt* is already a business day, returns *dt*.
    Otherwise, goes back until a business day is found.

    Args:
        dt: Starting date.

    Returns:
        The previous business day on or before *dt*.
    """
    while is_holiday(dt):
        dt -= timedelta(days=1)
    return dt


def adjust_due_date(dt: date, direction: str = "forward") -> date:
    """Adjust a due date to fall on a business day.

    Args:
        dt: The original due date.
        direction: 'forward' (next business day) or 'backward' (prev).

    Returns:
        Adjusted due date.
    """
    if direction == "forward":
        return next_business_day(dt)
    elif direction == "backward":
        return previous_business_day(dt)
    else:
        raise ValueError(f"invalid direction: {direction!r}")


def count_business_days(start: date, end: date) -> int:
    """Count the number of business days between two dates (exclusive of end).

    Args:
        start: Start date (inclusive).
        end: End date (exclusive).

    Returns:
        Number of business days.
    """
    count = 0
    current = start
    while current < end:
        if is_business_day(current):
            count += 1
        current += timedelta(days=1)
    return count


def add_business_days(dt: date, days: int) -> date:
    """Add a number of business days to a date.

    Args:
        dt: Starting date.
        days: Number of business days to add (may be negative).

    Returns:
        The resulting date.
    """
    if days >= 0:
        while days > 0:
            dt += timedelta(days=1)
            if is_business_day(dt):
                days -= 1
    else:
        while days < 0:
            dt -= timedelta(days=1)
            if is_business_day(dt):
                days += 1
    return dt


def is_second_saturday(dt: date) -> bool:
    """Check if a date is the second Saturday of its month.

    Some Indian banks treat second Saturdays as holidays.

    Args:
        dt: Date to check.

    Returns:
        True if it's a second Saturday.
    """
    if dt.weekday() != 5:
        return False
    return 8 <= dt.day <= 14


def is_fourth_saturday(dt: date) -> bool:
    """Check if a date is the fourth Saturday of its month.

    Some Indian banks treat fourth Saturdays as holidays.

    Args:
        dt: Date to check.

    Returns:
        True if it's a fourth Saturday.
    """
    if dt.weekday() != 5:
        return False
    return 22 <= dt.day <= 28
