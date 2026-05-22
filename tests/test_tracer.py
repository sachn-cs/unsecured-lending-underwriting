"""Tests for Tracer, Span, and SpanExporter."""

from __future__ import annotations

from underwrite.__tracer__ import ConsoleSpanExporter, Span, Tracer


class TestTracer:

    def test_start_span_creates_span(self) -> None:
        t = Tracer(service_id="test")
        span = t.start_span("op1")
        assert span.operation == "op1"
        assert span.service_id == "test"
        assert span.trace_id != ""

    def test_end_span_records_end_time(self) -> None:
        t = Tracer(service_id="test")
        span = t.start_span("op1")
        t.end_span(span)
        assert span.end_ms > 0
        assert len(t.spans) == 1

    def test_span_records_error(self) -> None:
        t = Tracer(service_id="test")
        span = t.start_span("op1")
        t.end_span(span, error="boom")
        assert span.error == "boom"

    def test_trace_context_manager_records_span(self) -> None:
        t = Tracer(service_id="test")
        with t.trace("ctx_op") as span:
            assert span.operation == "ctx_op"
        assert len(t.spans) == 1

    def test_trace_context_manager_records_exception(self) -> None:
        t = Tracer(service_id="test")
        try:
            with t.trace("fail_op"):
                raise ValueError("bad")
        except ValueError:
            pass
        assert len(t.spans) == 1
        assert t.spans[0].error != ""

    def test_exporter_called_on_end(self) -> None:
        exported: list = []

        class CaptureExporter:

            def export(self, spans: list) -> None:
                exported.extend(spans)

        t = Tracer(service_id="test", exporter=CaptureExporter())
        span = t.start_span("op1")
        t.end_span(span)
        assert len(exported) == 1

    def test_max_spans_evicts_oldest(self) -> None:
        t = Tracer(service_id="test", max_spans=3)
        for i in range(5):
            span = t.start_span(f"op{i}")
            t.end_span(span)
        assert len(t.spans) == 3
        # Oldest spans should be evicted
        ops = [s.operation for s in t.spans]
        assert "op0" not in ops
        assert "op1" not in ops
        assert "op2" in ops
        assert "op3" in ops
        assert "op4" in ops

    def test_max_spans_no_eviction_below_limit(self) -> None:
        t = Tracer(service_id="test", max_spans=10)
        for i in range(5):
            span = t.start_span(f"op{i}")
            t.end_span(span)
        assert len(t.spans) == 5

    def test_overflow_spans_exported(self) -> None:
        exported: list = []

        class CaptureExporter:

            def export(self, spans: list) -> None:
                exported.append(len(spans))

        t = Tracer(service_id="test", exporter=CaptureExporter(), max_spans=2)
        for i in range(4):
            span = t.start_span(f"op{i}")
            t.end_span(span)
        # Each end_span exports [span], plus one overflow export of [span0] and one of [span1]
        # Call 0: export([span0]) -> 1
        # Call 1: export([span1]) -> 1
        # Call 2: export([span2]) + overflow export([span0]) -> 1, 1
        # Call 3: export([span3]) + overflow export([span1]) -> 1, 1
        assert len(t.spans) == 2
        assert exported.count(1) >= 4  # each individual span exported


class TestConsoleSpanExporter:

    def test_export_does_not_raise(self) -> None:
        exporter = ConsoleSpanExporter()
        span = Span(trace_id="t",
                    span_id="s",
                    parent_span_id="p",
                    service_id="svc",
                    operation="op",
                    start_ms=0.0)
        span.end_ms = 1.0
        exporter.export([span])
