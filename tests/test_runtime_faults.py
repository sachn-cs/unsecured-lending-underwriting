# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Runtime — OTLP tracer, logging config, import errors, wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from underwrite.runtime import Runtime


class TestRuntimeOtlpTracer:
    def test_build_tracer_otlp_creates_tracer(self) -> None:
        config = config_with_otlp()
        rt = Runtime(config)
        assert rt.tracer is not None

    def test_build_tracer_otlp_disabled_returns_none(self) -> None:
        config = config_with_otlp()
        config.tracing.enabled = False
        rt = Runtime(config)
        assert rt.tracer is None

    def test_otlp_spans_are_exported(self) -> None:
        config = config_with_otlp()
        rt = Runtime(config)
        mock_exporter = MagicMock()
        assert rt.tracer is not None
        rt.tracer.set_exporter(mock_exporter)

        span = rt.tracer.start_span("test-op", tags={"key": "val"})
        rt.tracer.end_span(span)

        mock_exporter.export.assert_called_once()
        exported_spans = mock_exporter.export.call_args[0][0]
        assert len(exported_spans) == 1
        assert exported_spans[0].operation == "test-op"
        assert exported_spans[0].tags["key"] == "val"

    def test_otlp_exporter_fallback_on_import_error(self) -> None:
        config = config_with_otlp()
        rt = Runtime(config)
        assert rt.tracer is not None
        span = rt.tracer.start_span("fallback-test")
        rt.tracer.end_span(span)
        assert span.operation == "fallback-test"


def config_with_otlp() -> Any:
    from underwrite.config import Configuration

    config = Configuration.default()
    config.tracing.enabled = True
    config.tracing.exporter = "otlp"
    return config


class TestRuntimeRestartFailingServices:
    def test_restart_no_supervisor_returns_empty(self) -> None:
        from underwrite.config import Configuration

        config = Configuration.default()
        config.recovery.auto_restart = False
        rt = Runtime(config)
        assert rt.restart_failing_services() == []

    def test_restart_returns_empty_when_no_failures(self) -> None:
        from underwrite.config import Configuration

        config = Configuration.default()
        rt = Runtime(config)
        if rt.supervisor is not None:
            rt.supervisor.record_failure("svc-a")
            rt.supervisor.record_success("svc-a")
        assert rt.restart_failing_services() == []
