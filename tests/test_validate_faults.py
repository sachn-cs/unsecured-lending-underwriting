# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for validate.py — all 12 shared validation helpers."""

from __future__ import annotations

import math

import pytest

from underwrite.exceptions import ProtocolError
from underwrite.validate import PayloadValidator


class TestRequireNonEmpty:
    """Tests for require_non_empty — validates non-empty string."""

    def test_accepts_non_empty_string(self) -> None:
        assert PayloadValidator.require_non_empty("hello", "name") == "hello"

    def test_strips_whitespace(self) -> None:
        assert PayloadValidator.require_non_empty("  hello  ", "name") == "hello"

    def test_raises_for_empty_string(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator.require_non_empty("", "name")

    def test_raises_for_whitespace_only(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator.require_non_empty("   ", "name")

    def test_raises_for_none(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator.require_non_empty(None, "name")

    def test_raises_for_non_string(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator.require_non_empty(42, "name")


class TestRequireFinite:
    """Tests for require_finite — validates finite number."""

    def test_accepts_finite_float(self) -> None:
        assert PayloadValidator.require_finite(3.14, "rate") == 3.14

    def test_accepts_finite_int(self) -> None:
        assert PayloadValidator.require_finite(42, "count") == 42.0

    def test_accepts_numeric_string(self) -> None:
        assert PayloadValidator.require_finite("3.14", "rate") == 3.14

    def test_raises_for_nan(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_finite(math.nan, "rate")

    def test_raises_for_inf(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_finite(math.inf, "rate")

    def test_raises_for_neg_inf(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_finite(-math.inf, "rate")

    def test_raises_for_non_numeric(self) -> None:
        with pytest.raises(ProtocolError, match="must be a valid number"):
            PayloadValidator.require_finite("not-a-number", "rate")

    def test_raises_for_none(self) -> None:
        with pytest.raises(ProtocolError, match="must be a valid number"):
            PayloadValidator.require_finite(None, "rate")

    def test_raises_with_custom_name(self) -> None:
        with pytest.raises(ProtocolError, match="interest_rate"):
            PayloadValidator.require_finite(math.inf, "interest_rate")

    def test_accepts_zero(self) -> None:
        assert PayloadValidator.require_finite(0.0, "value") == 0.0

    def test_accepts_negative(self) -> None:
        assert PayloadValidator.require_finite(-10.5, "value") == -10.5


class TestRequirePositive:
    """Tests for require_positive — validates positive finite number."""

    def test_accepts_positive(self) -> None:
        assert PayloadValidator.require_positive(5.0, "amount") == 5.0

    def test_raises_for_zero(self) -> None:
        with pytest.raises(ProtocolError, match="must be positive"):
            PayloadValidator.require_positive(0.0, "amount")

    def test_raises_for_negative(self) -> None:
        with pytest.raises(ProtocolError, match="must be positive"):
            PayloadValidator.require_positive(-1.0, "amount")

    def test_raises_for_non_finite(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_positive(math.inf, "amount")


class TestRequireNonNegative:
    """Tests for require_non_negative — validates non-negative finite number."""

    def test_accepts_zero(self) -> None:
        assert PayloadValidator.require_non_negative(0.0, "value") == 0.0

    def test_accepts_positive(self) -> None:
        assert PayloadValidator.require_non_negative(10.0, "value") == 10.0

    def test_raises_for_negative(self) -> None:
        with pytest.raises(ProtocolError, match="must be non-negative"):
            PayloadValidator.require_non_negative(-0.1, "value")

    def test_raises_for_non_finite(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_non_negative(math.nan, "value")


class TestRequireInRange:
    """Tests for require_in_range — validates value in open interval."""

    def test_accepts_value_in_range(self) -> None:
        assert PayloadValidator.require_in_range(0.5, 0.0, 1.0, "prob") == 0.5

    def test_raises_for_value_below_lower_bound(self) -> None:
        with pytest.raises(ProtocolError, match="must be in"):
            PayloadValidator.require_in_range(-0.1, 0.0, 1.0, "prob")

    def test_raises_for_value_above_upper_bound(self) -> None:
        with pytest.raises(ProtocolError, match="must be in"):
            PayloadValidator.require_in_range(1.1, 0.0, 1.0, "prob")

    def test_accepts_value_at_lower_bound(self) -> None:
        assert PayloadValidator.require_in_range(0.0, 0.0, 1.0, "prob") == 0.0

    def test_accepts_value_at_upper_bound(self) -> None:
        assert PayloadValidator.require_in_range(1.0, 0.0, 1.0, "prob") == 1.0

    def test_raises_for_non_finite_value(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_in_range(math.inf, 0.0, 1.0, "prob")


class TestRequireMatch:
    """Tests for require_match — validates string matches regex pattern."""

    def test_accepts_matching_string(self) -> None:
        assert PayloadValidator.require_match(r"^\d{3}-\d{4}$", "555-1234", "zip") == "555-1234"

    def test_strips_whitespace(self) -> None:
        assert PayloadValidator.require_match(r"^\w+$", "  hello  ", "name") == "hello"

    def test_raises_for_non_match(self) -> None:
        with pytest.raises(ProtocolError, match="does not match"):
            PayloadValidator.require_match(r"^\d+$", "abc", "code")

    def test_raises_for_empty_string(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator.require_match(r"^\d+$", "", "code")

    def test_raises_for_none(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator.require_match(r"^\d+$", None, "code")


class TestGetNonEmpty:
    """Tests for get_non_empty — extracts non-empty string from payload."""

    def test_extracts_non_empty_value(self) -> None:
        payload = {"name": "Alice"}
        assert PayloadValidator().non_empty(payload, "name") == "Alice"

    def test_strips_whitespace(self) -> None:
        payload = {"name": "  Bob  "}
        assert PayloadValidator().non_empty(payload, "name") == "Bob"

    def test_uses_key_as_default_name(self) -> None:
        payload = {"name": "Charlie"}
        assert PayloadValidator().non_empty(payload, "name") == "Charlie"

    def test_raises_for_missing_key(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator().non_empty({}, "name")

    def test_raises_for_empty_value(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator().non_empty({"name": ""}, "name")

    def test_raises_for_none_value(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator().non_empty({"name": None}, "name")

    def test_uses_custom_name_in_error(self) -> None:
        with pytest.raises(ProtocolError, match="borrower"):
            PayloadValidator().non_empty({}, "name", name="borrower")


class TestGetFinite:
    """Tests for get_finite — extracts finite number from payload."""

    def test_extracts_finite_value(self) -> None:
        payload = {"rate": 0.05}
        assert PayloadValidator().finite(payload, "rate") == 0.05

    def test_returns_default_for_missing_key(self) -> None:
        payload: dict = {}
        assert PayloadValidator().finite(payload, "rate") == 0.0

    def test_returns_custom_default(self) -> None:
        payload: dict = {}
        assert PayloadValidator().finite(payload, "rate", default=1.0) == 1.0

    def test_raises_for_non_finite_value(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator().finite({"rate": math.inf}, "rate")

    def test_accepts_numeric_string(self) -> None:
        payload = {"rate": "0.05"}
        assert PayloadValidator().finite(payload, "rate") == 0.05

    def test_uses_custom_name_in_error(self) -> None:
        with pytest.raises(ProtocolError, match="interest"):
            PayloadValidator().finite({"rate": math.nan}, "rate", name="interest")


class TestGetPositive:
    """Tests for get_positive — extracts positive finite number from payload."""

    def test_extracts_positive_value(self) -> None:
        payload = {"amount": 100.0}
        assert PayloadValidator().positive(payload, "amount") == 100.0

    def test_returns_default_for_missing_key(self) -> None:
        payload: dict = {}
        assert PayloadValidator().positive(payload, "amount") == 1.0

    def test_returns_custom_default(self) -> None:
        payload: dict = {}
        assert PayloadValidator().positive(payload, "amount", default=5.0) == 5.0

    def test_raises_for_zero(self) -> None:
        with pytest.raises(ProtocolError, match="must be positive"):
            PayloadValidator().positive({"amount": 0.0}, "amount")

    def test_raises_for_negative(self) -> None:
        with pytest.raises(ProtocolError, match="must be positive"):
            PayloadValidator().positive({"amount": -5.0}, "amount")

    def test_raises_for_non_finite(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator().positive({"amount": math.inf}, "amount")


class TestGetNonNegative:
    """Tests for get_non_negative — extracts non-negative number from payload."""

    def test_extracts_zero(self) -> None:
        payload = {"value": 0.0}
        assert PayloadValidator().non_negative(payload, "value") == 0.0

    def test_extracts_positive(self) -> None:
        payload = {"value": 50.0}
        assert PayloadValidator().non_negative(payload, "value") == 50.0

    def test_returns_default_for_missing_key(self) -> None:
        payload: dict = {}
        assert PayloadValidator().non_negative(payload, "value") == 0.0

    def test_returns_custom_default(self) -> None:
        payload: dict = {}
        assert PayloadValidator().non_negative(payload, "value", default=10.0) == 10.0

    def test_raises_for_negative(self) -> None:
        with pytest.raises(ProtocolError, match="must be non-negative"):
            PayloadValidator().non_negative({"value": -1.0}, "value")

    def test_raises_for_non_finite(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator().non_negative({"value": math.nan}, "value")


class TestGetInRange:
    """Tests for get_in_range — extracts value in closed interval from payload."""

    def test_extracts_value_in_range(self) -> None:
        payload = {"score": 0.75}
        assert PayloadValidator().in_range(payload, "score", 0.0, 1.0, default=0.5) == 0.75

    def test_returns_default_for_missing_key(self) -> None:
        payload: dict = {}
        assert PayloadValidator().in_range(payload, "score", 0.0, 1.0, default=0.5) == 0.5

    def test_raises_for_out_of_range_above(self) -> None:
        with pytest.raises(ProtocolError, match="must be in"):
            PayloadValidator().in_range({"score": 1.5}, "score", 0.0, 1.0, default=0.5)

    def test_raises_for_out_of_range_below(self) -> None:
        with pytest.raises(ProtocolError, match="must be in"):
            PayloadValidator().in_range({"score": -0.1}, "score", 0.0, 1.0, default=0.5)

    def test_accepts_boundary_lower(self) -> None:
        assert PayloadValidator().in_range({"score": 0.0}, "score", 0.0, 1.0, default=0.5) == 0.0

    def test_accepts_boundary_upper(self) -> None:
        assert PayloadValidator().in_range({"score": 1.0}, "score", 0.0, 1.0, default=0.5) == 1.0

    def test_raises_for_non_finite(self) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator().in_range({"score": math.nan}, "score", 0.0, 1.0, default=0.5)


class TestGetMatch:
    """Tests for get_match — extracts regex-matched string from payload."""

    def test_extracts_matching_value(self) -> None:
        payload = {"code": "123-4567"}
        assert PayloadValidator().match(payload, "code", r"^\d{3}-\d{4}$") == "123-4567"

    def test_strips_whitespace(self) -> None:
        payload = {"code": "  555-1234  "}
        assert PayloadValidator().match(payload, "code", r"^\d{3}-\d{4}$") == "555-1234"

    def test_raises_for_non_match(self) -> None:
        with pytest.raises(ProtocolError, match="does not match"):
            PayloadValidator().match({"code": "abc"}, "code", r"^\d+$")


class TestRequirePan:
    """Tests for require_pan — ITD-compliant PAN validation."""

    @pytest.mark.parametrize("fourth", list("ABCEFGHJKLPT"))
    def test_accepts_valid_fourth_letter(self, fourth: str) -> None:
        pan = f"ABC{fourth}A1234A"
        assert PayloadValidator.require_pan(pan) == pan

    @pytest.mark.parametrize("fourth", list("DIMNOQRSUVWXYZ"))
    def test_rejects_invalid_fourth_letter(self, fourth: str) -> None:
        pan = f"ABC{fourth}A1234A"
        with pytest.raises(ProtocolError, match="status code"):
            PayloadValidator.require_pan(pan)

    def test_rejects_lowercase_pan_normalized(self) -> None:
        assert PayloadValidator.require_pan("abcpk1234a") == "ABCPK1234A"

    def test_raises_for_missing_key(self) -> None:
        with pytest.raises(ProtocolError, match="must be a non-empty string"):
            PayloadValidator().match({}, "code", r"^\d+$")

    def test_uses_custom_name_in_error(self) -> None:
        with pytest.raises(ProtocolError, match="phone"):
            PayloadValidator().match({"code": "abc"}, "code", r"^\d+$", name="phone")


class TestErrorMessages:
    """Tests that error messages include appropriate context."""

    def test_require_finite_mentions_type_for_non_numeric(self) -> None:
        with pytest.raises(ProtocolError, match="dict"):
            PayloadValidator.require_finite({"a": 1}, "value")

    def test_require_in_range_mentions_actual_value(self) -> None:
        with pytest.raises(ProtocolError, match="2.5"):
            PayloadValidator.require_in_range(2.5, 0.0, 1.0, "prob")

    def test_require_positive_mentions_actual_value(self) -> None:
        with pytest.raises(ProtocolError, match="-1"):
            PayloadValidator.require_positive(-1.0, "amount")
