# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for the value-object module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from underwrite.exceptions import ProtocolError
from underwrite.value_objects import (
    Money,
    Rate,
    application_id,
    loan_id,
    paise_to_rupees,
    rupees_to_paise,
    user_id,
)


class TestMoney:
    def test_from_rupees_rounds_to_paise(self) -> None:
        m = Money.from_rupees(Decimal("100.50"))
        assert m.paise == 10050
        assert m.rupees == Decimal("100.50")

    def test_from_rupees_accepts_float(self) -> None:
        m = Money.from_rupees(99.99)
        assert m.paise == 9999

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ProtocolError, match=">= 0"):
            Money(paise=-1)

    def test_currency_mismatch_rejected(self) -> None:
        a = Money(paise=100, currency="INR")
        b = Money(paise=100, currency="USD")
        with pytest.raises(ProtocolError, match="add"):
            _ = a + b

    def test_addition_same_currency(self) -> None:
        a = Money(paise=100)
        b = Money(paise=250)
        assert (a + b).paise == 350

    def test_subtraction_keeps_non_negative(self) -> None:
        with pytest.raises(ProtocolError, match="negative"):
            _ = Money(paise=100) - Money(paise=200)

    def test_bad_currency_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="alpha"):
            Money(paise=100, currency="IN1")


class TestRate:
    def test_from_fraction_basic(self) -> None:
        r = Rate.from_fraction(0.18)
        assert r.annual == Decimal("0.18")

    def test_from_fraction_accepts_str(self) -> None:
        r = Rate.from_fraction("0.075")
        assert r.annual == Decimal("0.075")

    def test_negative_rate_rejected(self) -> None:
        with pytest.raises(ProtocolError, match=">= 0"):
            Rate(annual=Decimal("-0.01"))

    def test_nan_rate_rejected(self) -> None:
        with pytest.raises(ProtocolError, match="finite"):
            Rate(annual=Decimal("NaN"))

    def test_monthly_property(self) -> None:
        r = Rate.from_fraction(0.12)
        assert r.monthly == Decimal("0.12") / Decimal("12")

    def test_daily_365_property(self) -> None:
        r = Rate.from_fraction(0.365)
        assert r.daily_365 == Decimal("0.365") / Decimal("365")

    def test_from_fraction_out_of_range(self) -> None:
        with pytest.raises(ProtocolError, match="out of range"):
            Rate.from_fraction(10.0)


class TestPaiseConversion:
    def test_paise_to_rupees(self) -> None:
        assert paise_to_rupees(100) == Decimal("1.00")

    def test_rupees_to_paise_rounds(self) -> None:
        assert rupees_to_paise(Decimal("1.005")) in (100, 101)
        assert rupees_to_paise(Decimal("1.00")) == 100

    def test_rupees_to_paise_rejects_nan(self) -> None:
        with pytest.raises(ProtocolError, match="finite"):
            rupees_to_paise(float("nan"))


class TestIds:
    def test_user_id_accepts_valid(self) -> None:
        assert user_id("alice_123") == "alice_123"

    def test_loan_id_accepts_valid(self) -> None:
        assert loan_id("L-100") == "L-100"

    def test_application_id_accepts_valid(self) -> None:
        assert application_id("app_42") == "app_42"

    @pytest.mark.parametrize("bad", ["", " ", "alice@example.com", "  alice", "x" * 200])
    def test_ids_reject_invalid(self, bad: str) -> None:
        with pytest.raises(ProtocolError):
            user_id(bad)
