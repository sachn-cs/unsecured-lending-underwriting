"""Tests for the centralised loguru logging and PII redaction.

Covers the public surface of :mod:`underwrite.__logger__`: message
redaction, the JSON and text formatters, and end-to-end behaviour through
a real loguru sink.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from underwrite.__logger__ import (
    SENSITIVE_LOG_FIELDS,
    JsonFormatter,
    TextFormatter,
    loguru_sink_format,
    redact,
)

if TYPE_CHECKING:
    from loguru import Record

DETERMINISTIC_LOG_TIME = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def make_record(message: str, *, level_name: str = "INFO") -> Record:
    """Captures a real loguru record for a message, with deterministic
    timestamp, module, line and logger name.

    loguru always stringifies a message before formatting, so *message* is
    a string that may be the serialised form of a structure.
    """
    captured: list[Record] = []

    def capture_record(record: Record) -> None:
        captured.append(record)

    patched = logger.patch(capture_record)
    handler_id = patched.add(lambda emitted: None, level="DEBUG", format="{message}")
    try:
        getattr(patched, level_name.lower())(message)
    finally:
        patched.remove(handler_id)
    record = captured[0]
    record["time"] = DETERMINISTIC_LOG_TIME
    record["module"] = "test_module"
    record["line"] = 42
    record["name"] = "underwrite.test"
    return record


def make_exception_record(message: str, *, level_name: str = "ERROR") -> Record:
    """Captures a real loguru record carrying a ``ValueError`` traceback."""
    captured: list[Record] = []

    def capture_record(record: Record) -> None:
        captured.append(record)

    patched = logger.patch(capture_record)
    handler_id = patched.add(lambda emitted: None, level="DEBUG", format="{message}")
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            getattr(patched.opt(exception=True), level_name.lower())(message)
    finally:
        patched.remove(handler_id)
    record = captured[0]
    record["time"] = DETERMINISTIC_LOG_TIME
    record["module"] = "test_module"
    record["line"] = 42
    record["name"] = "underwrite.test"
    return record


def capture(
    *emissions: Any,
    level: str = "DEBUG",
    formatter: JsonFormatter | TextFormatter | None = None,
) -> list[str]:
    """Emits through a real loguru sink using the given formatter."""
    records: list[str] = []
    sink_format = formatter or "{message}"
    if isinstance(sink_format, str):
        handler_id = logger.add(records.append, level=level, format=sink_format)
    else:
        handler_id = logger.add(records.append, level=level, format=loguru_sink_format(sink_format))
    try:
        for payload in emissions:
            if isinstance(payload, tuple):
                method, args = payload
                getattr(logger, method)(*args)
            else:
                logger.info(payload)
    finally:
        logger.remove(handler_id)
    return records


class TestRedact:
    def test_redacts_pan_field_in_payload(self) -> None:
        payload = {"customer_pan": "ABCDE1234F", "amount": 1000, "company": "Acme"}
        out = redact(payload)
        assert out == {
            "customer_pan": "***REDACTED***",
            "amount": 1000,
            "company": "Acme",
        }

    def test_does_not_overmatch_substring(self) -> None:
        """``company`` contains ``pan`` only as a substring and must not
        be redacted; ``panel_id`` must not be redacted either."""
        payload = {"company": "Acme", "panel_id": "panel_123", "author": "alice"}
        out = redact(payload)
        assert out == payload

    def test_redacts_nested_structures(self) -> None:
        payload = {
            "user": {"password": "hunter2", "name": "alice"},
            "tags": [{"token": "abc"}, {"role": "admin"}],
            "positions": ({"account": "1234"},),
        }
        out = redact(payload)
        assert out == {
            "user": {"password": "***REDACTED***", "name": "alice"},
            "tags": [{"token": "***REDACTED***"}, {"role": "admin"}],
            "positions": [{"account": "***REDACTED***"}],
        }

    def test_scalars_pass_through(self) -> None:
        assert redact("hello world") == "hello world"
        assert redact(42) == 42
        assert redact(None) is None

    def test_redacts_json_serialised_message(self) -> None:
        message = '{"customer_pan": "ABCDE1234F", "amount": 1000}'
        out = redact(message)
        assert out == {"customer_pan": "***REDACTED***", "amount": 1000}

    def test_redacts_repr_serialised_message(self) -> None:
        message = "{'customer_pan': 'ABCDE1234F', 'amount': 1000}"
        out = redact(message)
        assert out == {"customer_pan": "***REDACTED***", "amount": 1000}

    def test_redacts_serialised_list_message(self) -> None:
        out = redact('[{"pan": "ABCDE1234F"}, {"amount": 1000}]')
        assert out == [{"pan": "***REDACTED***"}, {"amount": 1000}]

    def test_scalar_serialised_string_passes_through(self) -> None:
        assert redact('"hello world"') == '"hello world"'
        assert redact("42") == "42"
        assert redact("True") == "True"

    def test_non_structure_message_passes_through(self) -> None:
        assert redact("pan value=ABCDE1234F in prose") == "pan value=ABCDE1234F in prose"

    def test_original_payload_is_not_mutated(self) -> None:
        payload = {"password": "hunter2"}
        redact(payload)
        assert payload == {"password": "hunter2"}

    def test_known_fields_are_sensitive(self) -> None:
        for field in SENSITIVE_LOG_FIELDS:
            assert redact({field: "value"}) == {field: "***REDACTED***"}


class TestJsonFormatter:
    def test_emits_expected_fields(self) -> None:
        record = make_record("{'message': 'hello', 'customer_pan': 'ABCDE1234F'}")
        out = json.loads(JsonFormatter().format(record))
        assert out["timestamp"] == "2026-01-02T03:04:05+0000"
        assert out["level"] == "INFO"
        assert out["logger"] == "underwrite"
        assert out["module"] == "test_module"
        assert out["line"] == 42
        assert out["message"] == {"message": "hello", "customer_pan": "***REDACTED***"}
        assert "correlation_id" not in out
        assert "exception" not in out

    def test_includes_exception_text_when_present(self) -> None:
        record = make_exception_record("operation failed", level_name="ERROR")
        out = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in out["exception"]
        assert out["level"] == "ERROR"

    def test_emits_single_line_json(self) -> None:
        record = make_record("hello")
        line = JsonFormatter().format(record)
        assert "\n" not in line.strip()

    def test_redacts_private_key_field(self) -> None:
        out = json.loads(JsonFormatter().format(make_record("{'private_key': 'abc', 'key_id': 'k1'}")))
        assert out["message"] == {"private_key": "***REDACTED***", "key_id": "k1"}


class TestTextFormatter:
    def test_emits_readable_line(self) -> None:
        record = make_record("hello world")
        line = TextFormatter().format(record)
        assert "2026-01-02 03:04:05 [INFO] underwrite: hello world" in line

    def test_includes_exception_text_when_present(self) -> None:
        record = make_exception_record("boom", level_name="CRITICAL")
        line = TextFormatter().format(record)
        assert "[CRITICAL]" in line
        assert "ValueError: boom" in line


class TestJsonTraceId:
    def test_trace_id_included_when_bound(self) -> None:
        lines: list[str] = []
        handler_id = logger.add(lines.append, level="DEBUG", format=loguru_sink_format(JsonFormatter()))
        try:
            logger.bind(trace_id="trace-1").info("hello")
        finally:
            logger.remove(handler_id)
        assert len(lines) == 1
        assert json.loads(lines[0])["trace_id"] == "trace-1"

    def test_trace_id_absent_when_not_bound(self) -> None:
        lines = capture(("info", ("hello",)), formatter=JsonFormatter())
        assert len(lines) == 1
        assert "trace_id" not in json.loads(lines[0])

    def test_non_string_trace_id_is_coerced(self) -> None:
        lines: list[str] = []
        handler_id = logger.add(lines.append, level="DEBUG", format=loguru_sink_format(JsonFormatter()))
        try:
            logger.bind(trace_id=12345).info("hello")
        finally:
            logger.remove(handler_id)
        assert len(lines) == 1
        assert json.loads(lines[0])["trace_id"] == "12345"


class TestLoguruIntegration:
    def test_json_sink_redacts_and_serializes(self) -> None:
        lines = capture(
            {"customer_pan": "ABCDE1234F", "amount": 1000},
            formatter=JsonFormatter(),
        )
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["message"] == {"customer_pan": "***REDACTED***", "amount": 1000}
        assert payload["logger"] == "underwrite"

    def test_positional_formatting_renders(self) -> None:
        lines = capture(
            ("info", ("disbursed {} to {} in {}", 42, "user_1", "INR")),
            formatter=TextFormatter(),
        )
        assert len(lines) == 1
        assert "disbursed 42 to user_1 in INR" in lines[0]

    def test_percent_style_args_are_not_substituted(self) -> None:
        """loguru does not substitute ``%``-style placeholders; the message
        is rendered literally. This locks in the requirement that all call
        sites use ``{}``-style formatting."""
        lines = capture(("info", ("saga %s step %d failed", "s1", 3)))
        assert lines == ["saga %s step %d failed\n"]

    def test_opt_exception_attaches_traceback(self) -> None:
        lines: list[str] = []
        handler_id = logger.add(lines.append, level="DEBUG", format=loguru_sink_format(JsonFormatter()))
        try:
            try:
                raise ValueError("boom")
            except ValueError:
                logger.opt(exception=True).error("operation failed")
        finally:
            logger.remove(handler_id)
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert "ValueError: boom" in payload["exception"]

    def test_levels_below_threshold_are_suppressed(self) -> None:
        lines = capture(
            ("debug", ("verbose detail",)),
            ("info", ("visible detail",)),
            level="INFO",
            formatter=JsonFormatter(),
        )
        assert len(lines) == 1
        assert json.loads(lines[0])["level"] == "INFO"

    def test_unredacted_passthrough_on_scalar_message(self) -> None:
        lines = capture(("info", ("hello world",)), formatter=JsonFormatter())
        payload = json.loads(lines[0])
        assert payload["message"] == "hello world"

    def test_nested_json_braces_survive_sink(self) -> None:
        """A structured message containing literal braces must round-trip
        through the loguru ``format_map`` stage unaltered."""
        lines = capture(
            {"note": "value {with} braces"},
            formatter=JsonFormatter(),
        )
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["message"] == {"note": "value {with} braces"}


class TestFormatterStateIndependence:
    def test_formatters_are_reusable(self) -> None:
        json_formatter = JsonFormatter()
        text_formatter = TextFormatter()
        first = json_formatter.format(make_record("one"))
        second = json_formatter.format(make_record("two"))
        assert json.loads(first)["message"] == "one"
        assert json.loads(second)["message"] == "two"
        assert "one" in text_formatter.format(make_record("one"))
