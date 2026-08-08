"""Centralised logging for the underwrite platform.

All services and infrastructure modules import ``logger`` from this
module instead of creating their own via ``logging.getLogger()``.
Logging configuration (level, output, format) is managed by
:func:`Runtime.__configure_logging` in :mod:`underwrite.__runtime__`.
"""

from __future__ import annotations

__all__ = [
    "SENSITIVE_LOG_FIELDS",
    "JsonFormatter",
    "TextFormatter",
    "logger",
    "loguru_sink_format",
    "redact",
]

import ast
import json
import re
import traceback
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

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

__FIELD_TOKEN_RE = re.compile(r"[a-z0-9]+")


def redact(data: object) -> object:
    """Returns a deep copy of *data* with sensitive log fields redacted.

    A field is redacted when any alphanumeric token of its name matches a
    known sensitive field, so innocent names that merely contain a keyword
    as a substring (e.g. ``company`` for ``pan``) are left untouched.

    loguru stringifies messages before formatting, so a rendered string
    that represents a dict or list is parsed back into a structure before
    redaction; any other value passes through unchanged.

    Args:
        data: The value to redact — typically a log message or payload.

    Returns:
        A new structure with sensitive values replaced by ``***REDACTED***``.
    """
    if isinstance(data, str):
        parsed = parse_serialised_message(data)
        if parsed is None or not isinstance(parsed, dict | list):
            return data
        data = parsed
    if isinstance(data, dict):
        out: dict[object, object] = {}
        for key, value in data.items():
            if isinstance(key, str) and (
                field_tokens(key) & SENSITIVE_LOG_FIELDS or key.lower() in SENSITIVE_LOG_FIELDS
            ):
                out[key] = "***REDACTED***"
            else:
                out[key] = redact(value)
        return out
    if isinstance(data, list | tuple):
        return [redact(item) for item in data]
    return data


def field_tokens(key: str) -> set[str]:
    """Splits a field name into lowercase alphanumeric tokens."""
    return set(__FIELD_TOKEN_RE.findall(key.lower()))


def parse_serialised_message(message: str) -> object | None:
    """Recovers a structure from a serialised message string.

    loguru always stringifies a message before formatting, so a structured
    payload arrives here as its string representation. Attempts a JSON
    parse first, then a Python literal parse.

    Args:
        message: The rendered message string.

    Returns:
        The parsed value when *message* serialises as a structure or a
        scalar, otherwise ``None``.
    """
    try:
        return json.loads(message)
    except ValueError:
        pass
    try:
        return ast.literal_eval(message)
    except (ValueError, SyntaxError):
        return None


def correlation_id() -> str:
    """Returns the current thread's correlation id, or an empty string."""
    from underwrite.services.base import get_log_correlation_id

    return get_log_correlation_id()


def exception_text(record: Record) -> str:
    """Formats a record's exception, or an empty string when absent."""
    exception = record.get("exception")
    if exception:
        return "\n" + "".join(traceback.format_exception(exception.type, exception.value, exception.traceback))
    return ""


def loguru_sink_format(
    formatter: JsonFormatter | TextFormatter,
) -> Callable[[Record], str]:
    """Returns a ``format`` callable ready for :func:`loguru.logger.add`.

    loguru treats a callable ``format`` as a dynamic *template* builder:
    its return value is run through ``str.format_map(record)`` before
    reaching the sink. Any literal braces in a rendered record therefore
    need escaping so the output survives ``format_map`` unaltered.
    """

    def build_template(record: Record) -> str:
        return formatter.format(record).replace("{", "{{").replace("}", "}}")

    return build_template


class JsonFormatter:
    """Serialises a loguru record to a redacted single-line JSON record.

    Args:
        record: The loguru record dictionary passed by the sink.

    Returns:
        A JSON line with redacted message and any exception traceback.
    """

    def format(self, record: Record) -> str:
        message = redact(record["message"])
        data: dict[str, object] = {
            "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": record["level"].name,
            "logger": "underwrite",
            "message": message,
            "module": record["module"],
            "line": record["line"],
        }
        corr = correlation_id()
        if corr:
            data["correlation_id"] = corr
        exception_line = exception_text(record)
        if exception_line:
            data["exception"] = exception_line
        return json.dumps(data)


class TextFormatter:
    """Formats a loguru record as human-readable text with correlation id.

    Args:
        record: The loguru record dictionary passed by the sink.

    Returns:
        A text line in ``time [LEVEL] correlation_id function: message``
        form, with any exception traceback appended.
    """

    def format(self, record: Record) -> str:
        message = redact(record["message"])
        if isinstance(message, dict | list):
            message = repr(message)
        corr = correlation_id()
        corr_prefix = f" {corr}" if corr else ""
        return (
            f"{record['time']:%Y-%m-%d %H:%M:%S}"
            f" [{record['level'].name}]{corr_prefix} {record['name']}: "
            f"{message}{exception_text(record)}"
        )
