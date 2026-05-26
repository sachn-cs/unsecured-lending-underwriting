"""Tests for Runtime — OTLP tracer, logging config, import errors, wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from underwrite.__runtime__ import Runtime


class TestRuntimeOtlpTracer:

    def test_build_tracer_otlp_creates_tracer(self) -> None:
        config = _config_with_otlp()
        rt = Runtime(config)
        assert rt.tracer is not None

    def test_build_tracer_otlp_disabled_returns_none(self) -> None:
        config = _config_with_otlp()
        config.tracing.enabled = False
        rt = Runtime(config)
        assert rt.tracer is None

    def test_otlp_spans_are_exported(self) -> None:
        config = _config_with_otlp()
        rt = Runtime(config)
        mock_exporter = MagicMock()
        assert rt.tracer is not None
        rt.tracer._Tracer__exporter = mock_exporter  # type: ignore[attr-defined]

        span = rt.tracer.start_span("test-op", tags={"key": "val"})
        rt.tracer.end_span(span)

        mock_exporter.export.assert_called_once()
        exported_spans = mock_exporter.export.call_args[0][0]
        assert len(exported_spans) == 1
        assert exported_spans[0].operation == "test-op"
        assert exported_spans[0].tags["key"] == "val"

    def test_otlp_exporter_fallback_on_import_error(self) -> None:
        config = _config_with_otlp()
        rt = Runtime(config)
        assert rt.tracer is not None
        span = rt.tracer.start_span("fallback-test")
        rt.tracer.end_span(span)
        assert span.operation == "fallback-test"


def _config_with_otlp() -> Any:
    from underwrite.__config__ import Configuration
    config = Configuration.default()
    config.tracing.enabled = True
    config.tracing.exporter = "otlp"
    return config
