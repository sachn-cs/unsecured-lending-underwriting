"""Tests for Indian number formatting utilities."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pytest

from underwrite.indian_format import (
    format_currency_symbol,
    format_indian_rupees,
    format_indian_words,
)


class TestFormatIndianRupees:
    def test_zero(self) -> None:
        assert format_indian_rupees(0) == "₹0.00"

    def test_simple_rupees(self) -> None:
        assert format_indian_rupees(100) == "₹100.00"

    def test_thousands(self) -> None:
        assert format_indian_rupees(1000) == "₹1,000.00"

    def test_lakhs(self) -> None:
        assert format_indian_rupees(100000) == "₹1,00,000.00"

    def test_crores(self) -> None:
        assert format_indian_rupees(10000000) == "₹1,00,00,000.00"

    def test_lakhs_and_thousands(self) -> None:
        assert format_indian_rupees(123456) == "₹1,23,456.00"

    def test_crores_lakhs_thousands(self) -> None:
        assert format_indian_rupees(123456789) == "₹12,34,56,789.00"

    def test_with_paise(self) -> None:
        assert format_indian_rupees(1234.56) == "₹1,234.56"

    def test_with_single_paisa(self) -> None:
        assert format_indian_rupees(100.5) == "₹100.50"

    def test_negative_amount(self) -> None:
        assert format_indian_rupees(-5000) == "-₹5,000.00"

    def test_large_crore_amount(self) -> None:
        assert format_indian_rupees(9876543210) == "₹9,87,65,43,210.00"

    def test_decimal_input(self) -> None:
        assert format_indian_rupees(Decimal("99999.99")) == "₹99,999.99"

    def test_fractional_paise_rounded(self) -> None:
        assert format_indian_rupees(Decimal("100.999")) == "₹101.00"

    def test_very_small_amount(self) -> None:
        assert format_indian_rupees(0.01) == "₹0.01"

    def test_invalid_infinite(self) -> None:
        with pytest.raises((ValueError, TypeError, InvalidOperation)):
            format_indian_rupees(float("inf"))

    def test_rupees_only_whole_number(self) -> None:
        assert format_indian_rupees(500) == "₹500.00"


class TestFormatIndianWords:
    def test_zero(self) -> None:
        assert format_indian_words(0) == "Zero Rupees"

    def test_single_digit(self) -> None:
        assert "Five" in format_indian_words(5)

    def test_rupees_contains_rupees_word(self) -> None:
        result = format_indian_words(100)
        assert "Rupees" in result

    def test_lakh(self) -> None:
        result = format_indian_words(100000)
        assert "Lakh" in result

    def test_crore(self) -> None:
        result = format_indian_words(10000000)
        assert "Crore" in result

    def test_thousand(self) -> None:
        result = format_indian_words(5000)
        assert "Thousand" in result

    def test_hundred(self) -> None:
        result = format_indian_words(500)
        assert "Hundred" in result

    def test_with_paise(self) -> None:
        result = format_indian_words(Decimal("100.50"))
        assert "Paise" in result

    def test_without_paise_flag(self) -> None:
        result = format_indian_words(Decimal("100.50"), include_paise=False)
        assert "Paise" not in result

    def test_negative_amount(self) -> None:
        result = format_indian_words(-1000)
        assert "Negative" in result

    def test_rupees_and_paise_both(self) -> None:
        result = format_indian_words(Decimal("12345.67"))
        assert "Rupees" in result
        assert "Paise" in result

    def test_exact_crore(self) -> None:
        result = format_indian_words(10000000)
        assert result == "One Crore Rupees"

    def test_exact_lakh(self) -> None:
        result = format_indian_words(100000)
        assert result == "One Lakh Rupees"

    def test_exact_thousand(self) -> None:
        result = format_indian_words(1000)
        assert result == "One Thousand Rupees"

    def test_complex_number(self) -> None:
        result = format_indian_words(1234567)
        assert "Crore" not in result or "Lakh" in result

    def test_very_large_number(self) -> None:
        result = format_indian_words(100000000)
        assert "Crore" in result

    def test_paisa_only(self) -> None:
        result = format_indian_words(Decimal("0.50"))
        assert "Paise" in result

    def test_rupee_paise_separator(self) -> None:
        result = format_indian_words(Decimal("1.01"))
        assert "and" in result or "Paise" in result

    def test_decimal_input(self) -> None:
        result = format_indian_words(Decimal("500"))
        assert "Five Hundred" in result


class TestFormatCurrencySymbol:
    def test_with_symbol(self) -> None:
        assert "₹" in format_currency_symbol(1000)

    def test_without_symbol(self) -> None:
        result = format_currency_symbol(1000, include_symbol=False)
        assert "₹" not in result

    def test_decimal_value(self) -> None:
        assert format_currency_symbol(Decimal("50000")) == "₹50,000.00"

    def test_format_matches_rupees(self) -> None:
        assert format_currency_symbol(123456.78) == format_indian_rupees(123456.78)
