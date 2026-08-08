"""Tests for PII detection and redaction."""

from __future__ import annotations

import pytest

from underwrite.__pii import contains_pii_value, is_pii_field, redact_payload


class TestPiiFieldDetection:
    @pytest.mark.parametrize(
        "field_name",
        ["aadhaar", "pan_number", "ssn", "phone_number", "email", "user_pin_code", "aadhaar_token", "mobile_number"],
    )
    def test_detects_pii_field(self, field_name: str) -> None:
        assert is_pii_field(field_name) is True

    @pytest.mark.parametrize("field_name", ["name", "amount", "company", "panel_id", "panchayat", "expandable", "author", "pinterest"])
    def test_non_pii_field(self, field_name: str) -> None:
        assert is_pii_field(field_name) is False


class TestPiiValueDetection:
    @pytest.mark.parametrize(
        "value",
        ["1234 5678 9012", "ABCDE1234F", "123-45-6789"],
    )
    def test_detects_pii_value(self, value: str) -> None:
        assert contains_pii_value(value) is True

    def test_non_pii_value(self) -> None:
        assert contains_pii_value("hello world") is False


class TestRedactPayload:
    def test_redacts_pii_field(self) -> None:
        result = redact_payload({"aadhaar": "123456789012"})
        assert result["aadhaar"] == "***REDACTED***"

    def test_redacts_pii_value(self) -> None:
        result = redact_payload({"note": "contact at 123-45-6789"})
        assert result["note"] == "***REDACTED***"

    def test_redacts_nested_dict(self) -> None:
        result = redact_payload({"user": {"pan": "ABCDE1234F"}})
        assert result["user"]["pan"] == "***REDACTED***"

    def test_redacts_nested_list(self) -> None:
        result = redact_payload({"items": [{"aadhaar": "123456789012"}]})
        assert result["items"][0]["aadhaar"] == "***REDACTED***"

    def test_preserves_non_pii(self) -> None:
        result = redact_payload({"name": "John", "amount": 100})
        assert result["name"] == "John"
        assert result["amount"] == 100

    def test_redacts_list_string_value(self) -> None:
        result = redact_payload({"contacts": ["123-45-6789", "hello"]})
        assert result["contacts"][0] == "***REDACTED***"

    def test_empty_payload(self) -> None:
        assert redact_payload({}) == {}

    def test_none_value_preserved(self) -> None:
        result = redact_payload({"key": None})
        assert result["key"] is None

    def test_unrelated_field_preserved(self) -> None:
        result = redact_payload({"company": "Acme", "amount": 100, "order_id": "L100"})
        assert result == {"company": "Acme", "amount": 100, "order_id": "L100"}
