# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Indian holiday calendar."""

from __future__ import annotations

from datetime import date

import pytest

from underwrite.calendar import (
    add_business_days,
    adjust_due_date,
    count_business_days,
    is_business_day,
    is_fourth_saturday,
    is_holiday,
    is_second_saturday,
    next_business_day,
    previous_business_day,
)


class TestHolidayDetection:
    def test_sunday_is_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 5)) is True

    def test_monday_not_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 6)) is False

    def test_first_saturday_not_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 4)) is False

    def test_second_saturday_is_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 11)) is True

    def test_third_saturday_not_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 18)) is False

    def test_fourth_saturday_is_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 25)) is True

    def test_republic_day_is_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 26)) is True

    def test_republic_day_2028(self) -> None:
        assert is_holiday(date(2028, 1, 26)) is True

    def test_diwali_2028(self) -> None:
        assert is_holiday(date(2028, 11, 4)) is True

    def test_diwali_2030(self) -> None:
        assert is_holiday(date(2030, 11, 13)) is True

    def test_calendar_works_past_2030(self) -> None:
        assert is_holiday(date(2031, 8, 15)) is True
        assert is_business_day(date(2031, 8, 15)) is False

    def test_independence_day_is_holiday(self) -> None:
        assert is_holiday(date(2025, 8, 15)) is True

    def test_gandhi_jayanti_is_holiday(self) -> None:
        assert is_holiday(date(2025, 10, 2)) is True

    def test_christmas_is_holiday(self) -> None:
        assert is_holiday(date(2025, 12, 25)) is True

    def test_new_year_is_holiday(self) -> None:
        assert is_holiday(date(2026, 1, 1)) is True

    def test_diwali_2025_is_holiday(self) -> None:
        assert is_holiday(date(2025, 10, 20)) is True

    def test_diwali_2026_is_holiday(self) -> None:
        assert is_holiday(date(2026, 11, 7)) is True

    def test_holi_2025_is_holiday(self) -> None:
        assert is_holiday(date(2025, 3, 14)) is True

    def test_holi_2026_is_holiday(self) -> None:
        assert is_holiday(date(2026, 3, 20)) is True

    def test_regular_tuesday_not_holiday(self) -> None:
        assert is_holiday(date(2025, 1, 14)) is False

    def test_labour_day_is_holiday(self) -> None:
        assert is_holiday(date(2025, 5, 1)) is True

    def test_good_friday_is_holiday(self) -> None:
        assert is_holiday(date(2025, 4, 18)) is True

    def test_ambedkar_jayanti_is_holiday(self) -> None:
        assert is_holiday(date(2025, 4, 14)) is True


class TestBusinessDay:
    def test_monday_is_business_day(self) -> None:
        assert is_business_day(date(2025, 1, 6)) is True

    def test_sunday_not_business_day(self) -> None:
        assert is_business_day(date(2025, 1, 5)) is False

    def test_first_saturday_is_business_day(self) -> None:
        assert is_business_day(date(2025, 1, 4)) is True

    def test_second_saturday_not_business_day(self) -> None:
        assert is_business_day(date(2025, 1, 11)) is False

    def test_fourth_saturday_not_business_day(self) -> None:
        assert is_business_day(date(2025, 1, 25)) is False

    def test_holiday_not_business_day(self) -> None:
        assert is_business_day(date(2025, 1, 26)) is False


class TestNextBusinessDay:
    def test_first_saturday_stays_same(self) -> None:
        assert next_business_day(date(2025, 1, 4)) == date(2025, 1, 4)

    def test_second_saturday_advances_to_monday(self) -> None:
        result = next_business_day(date(2025, 1, 11))
        assert result == date(2025, 1, 13)

    def test_sunday_advances_to_monday(self) -> None:
        result = next_business_day(date(2025, 1, 5))
        assert result == date(2025, 1, 6)

    def test_monday_stays_monday(self) -> None:
        d = date(2025, 1, 6)
        assert next_business_day(d) == d

    def test_christmas_to_next_business(self) -> None:
        result = next_business_day(date(2025, 12, 25))
        assert is_business_day(result) is True
        assert result == date(2025, 12, 26)

    def test_republic_day_2025(self) -> None:
        result = next_business_day(date(2025, 1, 26))
        assert result == date(2025, 1, 27)

    def test_fourth_saturday_advances(self) -> None:
        result = next_business_day(date(2025, 1, 25))
        assert result == date(2025, 1, 27)


class TestPreviousBusinessDay:
    def test_monday_goes_back_to_friday(self) -> None:
        result = previous_business_day(date(2025, 1, 6))
        assert result == date(2025, 1, 6)

    def test_sunday_goes_back_to_saturday(self) -> None:
        result = previous_business_day(date(2025, 1, 5))
        assert result >= date(2025, 1, 4)

    def test_first_saturday_stays_same(self) -> None:
        d = date(2025, 1, 4)
        assert previous_business_day(d) == d

    def test_monday_stays_monday_prev(self) -> None:
        d = date(2025, 1, 6)
        assert previous_business_day(d) == d


class TestAdjustDueDate:
    def test_forward_from_holiday(self) -> None:
        result = adjust_due_date(date(2025, 1, 26), direction="forward")
        assert is_business_day(result) is True
        assert result == date(2025, 1, 27)

    def test_backward_from_holiday(self) -> None:
        result = adjust_due_date(date(2025, 1, 26), direction="backward")
        assert is_business_day(result) is True
        assert result == date(2025, 1, 24)

    def test_invalid_direction(self) -> None:
        with pytest.raises(ValueError, match="invalid direction"):
            adjust_due_date(date(2025, 1, 1), direction="invalid")


class TestCountBusinessDays:
    def test_same_day_zero(self) -> None:
        assert count_business_days(date(2025, 1, 6), date(2025, 1, 6)) == 0

    def test_one_week(self) -> None:
        count = count_business_days(date(2025, 1, 6), date(2025, 1, 13))
        assert count == 5

    def test_two_weeks(self) -> None:
        count = count_business_days(date(2025, 1, 6), date(2025, 1, 20))
        assert count == 11

    def test_one_business_day(self) -> None:
        assert count_business_days(date(2025, 1, 6), date(2025, 1, 7)) == 1


class TestAddBusinessDays:
    def test_add_zero(self) -> None:
        d = date(2025, 1, 6)
        assert add_business_days(d, 0) == d

    def test_add_one_from_monday(self) -> None:
        assert add_business_days(date(2025, 1, 6), 1) == date(2025, 1, 7)

    def test_add_one_from_friday_to_saturday(self) -> None:
        result = add_business_days(date(2025, 1, 3), 1)
        assert is_business_day(result) is True
        assert result >= date(2025, 1, 4)

    def test_add_ten(self) -> None:
        d = date(2025, 1, 6)
        result = add_business_days(d, 10)
        assert is_business_day(result) is True
        assert (result - d).days >= 12

    def test_subtract_one_from_tuesday(self) -> None:
        result = add_business_days(date(2025, 1, 7), -1)
        assert is_business_day(result) is True
        assert result == date(2025, 1, 6)

    def test_subtract_one_from_monday_to_friday(self) -> None:
        result = add_business_days(date(2025, 1, 6), -1)
        assert is_business_day(result) is True

    def test_add_through_holidays(self) -> None:
        d = date(2025, 12, 24)
        result = add_business_days(d, 3)
        assert is_business_day(result) is True

    def test_negative_add(self) -> None:
        d = date(2025, 1, 10)
        result = add_business_days(d, -5)
        assert is_business_day(result) is True


class TestSecondFourthSaturday:
    def test_second_saturday_jan_2025(self) -> None:
        assert is_second_saturday(date(2025, 1, 11)) is True

    def test_first_saturday_not_second(self) -> None:
        assert is_second_saturday(date(2025, 1, 4)) is False

    def test_third_saturday_not_second(self) -> None:
        assert is_second_saturday(date(2025, 1, 18)) is False

    def test_fourth_saturday_jan_2025(self) -> None:
        assert is_fourth_saturday(date(2025, 1, 25)) is True

    def test_non_saturday_not_fourth(self) -> None:
        assert is_fourth_saturday(date(2025, 1, 22)) is False
