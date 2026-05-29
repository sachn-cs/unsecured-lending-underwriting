"""Distributed tracing — span propagation and export.

Each event carries trace context.  Spans are created for handler
execution and exported to a configurable backend (no-op by default).
"""

from __future__ import annotations

__all__ = [
    "ConsoleSpanExporter",
    "OtlpSpanExporter",
    "Span",
    "SpanContext",
    "SpanExporter",
    "Tracer",
]

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single trace span — duration, tags, and error state."""

    trace_id: str
    span_id: str
    parent_span_id: str
    service_id: str
    operation: str
    start_ms: float
    end_ms: float = 0.0
    tags: dict[str, str] = field(default_factory=dict)
    error: str = ""


class SpanExporter:
    """Exports completed spans to a backend.  No-op by default."""

    def export(self, spans: list[Span]) -> None:
        """Exports completed spans.  No-op by default.

        Args:
            spans: Completed spans to export.
        """


class Tracer:
    """Creates and manages spans for a service."""

    def __init__(self,
                 service_id: str,
                 exporter: SpanExporter | None = None,
                 max_spans: int = 10000) -> None:
        self.__service_id: str = service_id
        self.__exporter: SpanExporter = exporter or SpanExporter()
        self.__lock: threading.Lock = threading.Lock()
        self.__spans: list[Span] = []
        self.__max_spans: int = max_spans

    @property
    def spans(self) -> list[Span]:
        """Returns a snapshot of all completed spans."""
        with self.__lock:
            return list(self.__spans)

    def start_span(self,
                   operation: str,
                   trace_id: str = "",
                   parent_span_id: str = "",
                   tags: dict[str, str] | None = None) -> Span:
        """Creates and returns a new span without ending it.

        Args:
            operation: Name of the traced operation.
            trace_id: Trace ID (auto-generated if empty).
            parent_span_id: Parent span ID for nesting.
            tags: Key-value tags to attach.

        Returns:
            The newly created span.
        """
        span = Span(
            trace_id=trace_id or str(uuid.uuid4()),
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            service_id=self.__service_id,
            operation=operation,
            start_ms=time.perf_counter() * 1000.0,
            tags=tags or {},
        )
        return span

    def end_span(self, span: Span, error: str = "") -> None:
        """Completes a span and exports it.

        Args:
            span: The span to end.
            error: Optional error description.
        """
        span.end_ms = time.perf_counter() * 1000.0
        span.error = error
        overflow: list[Span] = []
        with self.__lock:
            self.__spans.append(span)
            if len(self.__spans) > self.__max_spans:
                overflow = self.__spans[:-self.__max_spans]
                self.__spans = self.__spans[-self.__max_spans:]
        self.__exporter.export([span])
        if overflow:
            self.__exporter.export(overflow)

    def trace(self,
              operation: str,
              trace_id: str = "",
              parent_span_id: str = "",
              tags: dict[str, str] | None = None) -> SpanContext:
        """Returns a context manager that starts/ends a span automatically.

        Args:
            operation: Name of the traced operation.
            trace_id: Trace ID (auto-generated if empty).
            parent_span_id: Parent span ID for nesting.
            tags: Key-value tags to attach.

        Returns:
            A ``SpanContext`` context manager.
        """
        return SpanContext(self, operation, trace_id, parent_span_id, tags or
                           {})


class SpanContext:
    """Context manager that starts a span on enter and ends it on exit."""

    def __init__(self, tracer: Tracer, operation: str, trace_id: str,
                 parent_span_id: str, tags: dict[str, str]) -> None:
        self.__tracer = tracer
        self.__operation = operation
        self.__trace_id = trace_id
        self.__parent_span_id = parent_span_id
        self.__tags = tags
        self.__span: Span | None = None

    def __enter__(self) -> Span:
        self.__span = self.__tracer.start_span(
            self.__operation,
            self.__trace_id,
            self.__parent_span_id,
            self.__tags,
        )
        return self.__span

    def __exit__(self, *args: Any) -> None:
        if self.__span is None:
            return
        error = ""
        if args[0] is not None:
            error = str(args[1]) if args[1] else str(args[0])
        self.__tracer.end_span(self.__span, error=error)


class ConsoleSpanExporter(SpanExporter):
    """Exports spans to stdout for development."""

    def export(self, spans: list[Span]) -> None:
        """Prints span details to stdout.

        Args:
            spans: Completed spans to print.
        """
        for span in spans:
            duration = span.end_ms - span.start_ms
            tag_str = " ".join(f"{k}={v}" for k, v in span.tags.items())
            err = f" ERROR={span.error}" if span.error else ""
            print(
                f"[trace] {span.trace_id[:8]} {span.service_id}.{span.operation} "
                f"{duration:.1f}ms parent={span.parent_span_id[:8]}{err} {tag_str}"
            )


class OtlpSpanExporter(SpanExporter):
    """Exports spans via OpenTelemetry OTLP.

    Requires the ``otlp`` extra (``opentelemetry-api``,
    ``opentelemetry-sdk``, ``opentelemetry-exporter-otlp``).
    """

    def __init__(self,
                 endpoint: str = "http://localhost:4317",
                 service_name: str = "underwrite") -> None:
        self.__endpoint = endpoint
        self.__service_name = service_name

    def export(self, spans: list[Span]) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as _OTLPSpanExporter,)
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            logger.warning(
                "OTLP exporter not available; install with: pip install underwrite[otlp]"
            )
            return

        resource = Resource.create({"service.name": self.__service_name})
        provider = SdkTracerProvider(resource=resource)
        exporter = _OTLPSpanExporter(endpoint=self.__endpoint)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        for span in spans:
            sdk_span = provider.get_tracer(__name__).start_span(
                span.operation,
                attributes={
                    **span.tags,
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "service_id": span.service_id,
                    "duration_ms": f"{span.end_ms - span.start_ms:.1f}",
                },
            )
            if span.error:
                sdk_span.set_status(
                    trace.Status(trace.StatusCode.ERROR, span.error))
            sdk_span.end()

        processor.shutdown()
        provider.shutdown()
