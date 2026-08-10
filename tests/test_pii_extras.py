# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for PIISanitizer domain service class."""

from __future__ import annotations

from underwrite.pii import PII_REDACTED, PIISanitizer


class TestPIISanitizer:
    def test_sanitize_leaves_clean_payload(self) -> None:
        result = PIISanitizer.sanitize({"name": "John", "amount": 100})
        assert result == {"name": "John", "amount": 100}

    def test_sanitize_redacts_pii_field(self) -> None:
        result = PIISanitizer.sanitize({"aadhaar": "123456789012"})
        assert result["aadhaar"] == PII_REDACTED

    def test_sanitize_redacts_pii_value(self) -> None:
        result = PIISanitizer.sanitize({"note": "contact at 123-45-6789"})
        assert result["note"] == PII_REDACTED

    def test_sanitize_redacts_nested_dict(self) -> None:
        result = PIISanitizer.sanitize({"user": {"pan": "ABCDE1234F"}})
        assert result["user"]["pan"] == PII_REDACTED

    def test_sanitize_redacts_nested_list(self) -> None:
        result = PIISanitizer.sanitize({"items": [{"aadhaar": "123456789012"}]})
        assert result["items"][0]["aadhaar"] == PII_REDACTED

    def test_sanitize_handles_empty_dict(self) -> None:
        assert PIISanitizer.sanitize({}) == {}

    def test_sanitize_handles_none_value(self) -> None:
        result = PIISanitizer.sanitize({"key": None})
        assert result["key"] is None

    def test_sanitize_redacts_list_string_value(self) -> None:
        result = PIISanitizer.sanitize({"contacts": ["123-45-6789", "hello"]})
        assert result["contacts"][0] == PII_REDACTED
        assert result["contacts"][1] == "hello"

    def test_is_sensitive_field_detects_pii(self) -> None:
        assert PIISanitizer.is_sensitive_field("aadhaar") is True
        assert PIISanitizer.is_sensitive_field("pan") is True
        assert PIISanitizer.is_sensitive_field("email_address") is True
        assert PIISanitizer.is_sensitive_field("name") is False

    def test_contains_sensitive_value_detects_patterns(self) -> None:
        assert PIISanitizer.contains_sensitive_value("123456789012") is True
        assert PIISanitizer.contains_sensitive_value("ABCDE1234F") is True
        assert PIISanitizer.contains_sensitive_value("hello") is False
