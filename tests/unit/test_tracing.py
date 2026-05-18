"""Unit tests for tracing stub."""

from __future__ import annotations

from ulu.infra.tracing import NoOpTracer, Span, Tracer


class TestTracer:
    def test_start_span(self) -> None:
        tracer = Tracer("test")
        span = tracer.start_span("op1", attributes={"key": "value"})
        assert isinstance(span, Span)
        assert span.name == "op1"
        assert span.attributes["key"] == "value"
        assert len(tracer.spans) == 1

    def test_span_context_manager(self) -> None:
        tracer = Tracer("test")
        with tracer.span("op2") as span:
            span.set_attribute("foo", "bar")
            span.add_event("event1")
        assert span.end_time is not None
        assert span.duration_ms() >= 0
        assert span.attributes["foo"] == "bar"

    def test_span_add_event(self) -> None:
        tracer = Tracer("test")
        with tracer.span("op3") as span:
            span.add_event("evt", {"a": 1})
        assert len(span.events) == 1
        assert span.events[0]["name"] == "evt"

    def test_noop_tracer(self) -> None:
        tracer = NoOpTracer()
        with tracer.span("noop") as span:
            span.set_attribute("x", "y")
        assert len(tracer.spans) == 0


class TestSpan:
    def test_duration_ms(self) -> None:
        import time

        span = Span("id", "name", time.time())
        time.sleep(0.01)
        span.end()
        assert span.duration_ms() >= 10.0
