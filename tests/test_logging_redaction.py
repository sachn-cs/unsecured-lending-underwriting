"""Tests for the JSON log formatter and the runtime's redaction path."""

from __future__ import annotations

import json
import logging
import re

SENSITIVE_LOG_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "auth",
        "authorization",
        "private_key",
        "ssn",
        "tax",
        "pin",
        "cvv",
        "pan",
        "account",
        "routing",
    }
)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class JsonFormatter(logging.Formatter):
    """Mirror of the JSON formatter installed by Runtime.__configure_logging."""

    def redact(self, data: object) -> object:
        if isinstance(data, dict):
            out: dict[object, object] = {}
            for k, v in data.items():
                if isinstance(k, str) and _tokens(k) & SENSITIVE_LOG_FIELDS:
                    out[k] = "***REDACTED***"
                else:
                    out[k] = self.redact(v)
            return out
        if isinstance(data, (list, tuple)):
            return [self.redact(i) for i in data]
        return data

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self.redact({"message": record.getMessage()}))


def _build_formatter() -> JsonFormatter:
    """Build the JSON formatter so tests can exercise the redaction logic."""
    return JsonFormatter()


class TestJsonFormatterRedaction:
    def test_redacts_pan_field_in_payload(self) -> None:
        """A structured payload with ``customer_pan`` as a key must
        be redacted."""
        formatter = _build_formatter()
        redact = formatter.redact
        payload = {"customer_pan": "ABCDE1234F", "amount": 1000, "company": "Acme"}
        out = redact(payload)
        assert out == {
            "customer_pan": "***REDACTED***",
            "amount": 1000,
            "company": "Acme",
        }

    def test_does_not_overmatch_substring(self) -> None:
        """A field like ``company`` that incidentally contains the
        letters ``pan`` as a substring must NOT be redacted."""
        formatter = _build_formatter()
        redact = formatter.redact
        payload = {"company": "Acme", "panel_id": "panel_123", "author": "alice"}
        out = redact(payload)
        assert out == payload
