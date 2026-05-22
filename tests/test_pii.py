"""Tests for PII detection and redaction."""

from __future__ import annotations

from underwrite.__pii import contains_pii_value, is_pii_field, redact_payload


class TestPiiFieldDetection:

    def test_detects_aadhaar_field(self) -> None:
        assert is_pii_field("aadhaar") is True

    def test_detects_pan_field(self) -> None:
        assert is_pii_field("pan_number") is True

    def test_detects_ssn_field(self) -> None:
        assert is_pii_field("ssn") is True

    def test_detects_phone_field(self) -> None:
        assert is_pii_field("phone_number") is True

    def test_detects_email_field(self) -> None:
        assert is_pii_field("email") is True

    def test_non_pii_field(self) -> None:
        assert is_pii_field("name") is False
        assert is_pii_field("amount") is False


class TestPiiValueDetection:

    def test_detects_aadhaar_value(self) -> None:
        assert contains_pii_value("1234 5678 9012") is True

    def test_detects_pan_value(self) -> None:
        assert contains_pii_value("ABCDE1234F") is True

    def test_detects_ssn_value(self) -> None:
        assert contains_pii_value("123-45-6789") is True

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
