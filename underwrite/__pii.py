"""PII detection and redaction for audit payloads.

Defines patterns for personally identifiable information fields
and provides a redaction function that sanitizes matching values.
"""

from __future__ import annotations

__all__ = [
    "PII_FIELD_PATTERNS",
    "PII_REDACTED",
    "PII_VALUE_PATTERNS",
    "contains_pii_value",
    "is_pii_field",
    "redact_payload",
]

import re
from typing import Any

PII_FIELD_PATTERNS: list[str] = [
    "aadhaar",
    "pan",
    "ssn",
    "tax_id",
    "passport",
    "driving_license",
    "voter_id",
    "phone",
    "mobile",
    "email",
    "account_number",
    "ifsc",
    "bank_account",
]

PII_VALUE_PATTERNS: list[str] = [
    r"\b\d{4}\s?\d{4}\s?\d{4}\b",  # Aadhaar-like (12 digits)
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",  # PAN-like (10 chars)
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN-like
    r"\b[A-Z]{1,2}\d{6,9}\b",  # Passport-like
]

PII_REDACTED: str = "***REDACTED***"


def is_pii_field(key: str) -> bool:
    """Returns True if the key matches a known PII field name."""
    lower = key.lower().replace("_", "").replace("-", "")
    for pattern in PII_FIELD_PATTERNS:
        if pattern.replace("_", "") in lower:
            return True
    return False


def contains_pii_value(value: str) -> bool:
    """Returns True if the string value matches a PII pattern."""
    for pat in PII_VALUE_PATTERNS:
        if re.search(pat, value):
            return True
    return False


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a copy of payload with PII fields and values redacted."""
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if is_pii_field(key):
            result[key] = PII_REDACTED
        elif isinstance(value, str) and contains_pii_value(value):
            result[key] = PII_REDACTED
        elif isinstance(value, dict):
            result[key] = redact_payload(value)
        elif isinstance(value, list):
            result[key] = [
                redact_payload(item) if isinstance(item, dict) else PII_REDACTED
                if isinstance(item, str) and contains_pii_value(item) else item
                for item in value
            ]
        else:
            result[key] = value
    return result
