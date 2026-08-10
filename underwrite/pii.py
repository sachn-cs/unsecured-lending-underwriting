"""PII detection and redaction for audit payloads.

Defines patterns for personally identifiable information fields
and provides a redaction function that sanitizes matching values.
"""

from __future__ import annotations

__all__ = [
    "PII_FIELD_PATTERNS",
    "PII_REDACTED",
    "PII_VALUE_PATTERNS",
    "PIISanitizer",
    "redact",
    "redact_event",
]

import re
from typing import Any


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a deep copy of *payload* with PII fields and values redacted.

    Args:
        payload: The source data dictionary.

    Returns:
        A new dictionary with sensitive content replaced by ``PII_REDACTED``.
    """
    return PIISanitizer.sanitize(payload)


def redact_event(event: Any) -> Any:
    """Returns a copy of *event* with PII fields and values redacted.

    The DLQ, the audit ledger, and the Prometheus label pipeline
    are all read by humans or scraped by monitoring systems and
    must not carry PAN, Aadhaar, mobile numbers, etc. The redacted
    copy is what they observe; the in-flight event in memory is
    untouched.

    Args:
        event: The Event whose payload is to be redacted.

    Returns:
        A new Event with sensitive content in the payload replaced
        by ``PII_REDACTED``. Returns the same object if no change.
    """
    from underwrite.events import Event

    sanitized_payload = redact(dict(event.payload))
    if sanitized_payload == event.payload:
        return event
    return Event(
        event_id=event.event_id,
        event_type=event.event_type,
        source=event.source,
        source_key=event.source_key,
        timestamp=event.timestamp,
        payload=sanitized_payload,
        correlation_id=event.correlation_id,
        signature=event.signature,
        trace_id=event.trace_id,
        parent_span_id=event.parent_span_id,
    )


PII_FIELD_PATTERNS: list[str] = [
    "aadhaar",
    "account",
    "bank",
    "ckyc",
    "credit",
    "demate",
    "dob",
    "driving_license",
    "email",
    "esic",
    "folio",
    "ifsc",
    "license",
    "mobile",
    "passport",
    "pan",
    "phone",
    "pin",
    "pincode",
    "ssn",
    "tax",
    "uan",
    "urn",
    "voter",
]

PII_VALUE_PATTERNS: list[str] = [
    r"\b\d{4}\s?\d{4}\s?\d{4}\b",  # Aadhaar-like (12 digits)
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",  # PAN-like (10 chars)
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN-like (with dashes)
    r"\b\d{9}\b",  # SSN-like (undashed, 9 digits)
    r"\b[A-Z]{1,2}\d{6,9}\b",  # Passport-like
    r"\b(?:\+91|91|0)?[6-9]\d{9}\b",  # Indian mobile
    r"\b[1-9][0-9]{5}\b",  # Indian PIN code
    r"\b[A-Z]{4}0[A-Z0-9]{6}\b",  # IFSC code
    r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",  # GSTIN
    r"\b[A-Z]{3}[0-9]{7}\b",  # Voter ID
    r"\b[A-Z][0-9]{7}\b",  # Passport (India)
    r"\b[A-Z]{2}[0-9]{2}\s?[0-9]{11}\b",  # Driving license (India)
    r"\bCKYC[0-9]{10,16}\b",  # CKYC number
    r"\b[1-9][0-9]{11}\b",  # EPFO UAN (12-digit)
]

PII_REDACTED: str = "***REDACTED***"

PII_FIELD_TOKEN_RE = re.compile(r"[a-z0-9]+")


def field_tokens(key: str) -> set[str]:
    """Splits a field name into lowercase alphanumeric tokens."""
    return set(PII_FIELD_TOKEN_RE.findall(key.lower()))


class PIISanitizer:
    """Domain service for PII detection and redaction.

    Inspects payload dictionaries for known PII field names and value
    patterns, returning a deep copy with sensitive values replaced by a
    redaction sentinel.
    """

    @staticmethod
    def is_sensitive_field(key: str) -> bool:
        """Returns True if any token of *key* matches a known PII field name.

        Matching is token-based: the key is split into alphanumeric
        tokens and matched against the canonical PII field names. This
        avoids the previous substring-after-underscore-strip behaviour
        that over-matched innocent field names like ``company`` for
        the ``pan`` pattern.
        """
        tokens = field_tokens(key)
        if not tokens:
            return False
        for pattern in PII_FIELD_PATTERNS:
            if pattern in tokens:
                return True
        return False

    @staticmethod
    def contains_sensitive_value(value: str) -> bool:
        """Returns True if the string value matches a PII pattern."""
        for pat in PII_VALUE_PATTERNS:
            if re.search(pat, value):
                return True
        return False

    @staticmethod
    def redact_str(text: str) -> str:
        """Redacts PII values within a larger string.

        Args:
            text: The source string.

        Returns:
            The string with any PII values replaced by ``PII_REDACTED``.
        """
        for pat in PII_VALUE_PATTERNS:
            text = re.sub(pat, PII_REDACTED, text)
        return text

    @staticmethod
    def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
        """Returns a deep copy of *payload* with PII fields and values redacted.

        Args:
            payload: The source data dictionary.

        Returns:
            A new dictionary with sensitive content replaced by ``PII_REDACTED``.
        """
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if PIISanitizer.is_sensitive_field(key):
                result[key] = PII_REDACTED
            elif isinstance(value, str) and PIISanitizer.contains_sensitive_value(value):
                result[key] = PII_REDACTED
            elif isinstance(value, dict):
                result[key] = PIISanitizer.sanitize(value)
            elif isinstance(value, list):
                result[key] = [
                    PIISanitizer.sanitize(item)
                    if isinstance(item, dict)
                    else PII_REDACTED
                    if isinstance(item, str) and PIISanitizer.contains_sensitive_value(item)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
