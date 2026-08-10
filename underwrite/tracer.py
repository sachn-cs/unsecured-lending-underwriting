"""Distributed tracing — span propagation and export.

Each event carries trace context.  Spans are created for handler
execution and exported to a configurable backend (no-op by default).
"""

from __future__ import annotations

__all__ = [
    "Console",
    "Otlp",
    "Span",
    "SpanContext",
    "SpanExporter",
    "Tracer",
]

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from underwrite.logger import logger


@dataclass(slots=True)
class Span:
    """A single trace span — duration, tags, and error state."""

    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    operation: str
    start_ms: float
    end_ms: float = 0.0
    tags: dict[str, str] = field(default_factory=dict)
    error: str = ""


class SpanExporter:
    """Exports completed spans to a backend.  No-op by default."""

    def export(self, spans: list[Span]) -> None:
        """Exports completed spans.  Logs span count in the base implementation.

        Args:
            spans: Completed spans to export.
        """
        if spans:
            logger.debug("exporting {} spans (no-op base exporter)", len(spans))


class Tracer:
    """Creates and manages spans for a service."""

    def __init__(self, name: str, exporter: SpanExporter | None = None, max_spans: int = 10000) -> None:
        self.__name: str = name
        self.__exporter: SpanExporter = exporter or SpanExporter()
        self.__lock: threading.Lock = threading.Lock()
        self.__spans: list[Span] = []
        self.__max_spans: int = max_spans

    @property
    def spans(self) -> list[Span]:
        """Returns a snapshot of all completed spans."""
        with self.__lock:
            return list(self.__spans)

    @property
    def exporter(self) -> SpanExporter:
        """Returns the exporter (test-accessible hook)."""
        return self.__exporter

    @exporter.setter
    def exporter(self, exporter: SpanExporter) -> None:
        with self.__lock:
            self.__exporter = exporter

    def start_span(
        self, operation: str, trace_id: str = "", parent_span_id: str = "", tags: dict[str, str] | None = None
    ) -> Span:
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
            name=self.__name,
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
        with self.__lock:
            self.__spans.append(span)
            if len(self.__spans) > self.__max_spans:
                overflow = self.__spans[: -self.__max_spans]
                self.__spans = self.__spans[-self.__max_spans :]
                logger.warning("tracer span overflow: dropping {} spans", len(overflow))
        self.__exporter.export([span])

    def trace(
        self, operation: str, trace_id: str = "", parent_span_id: str = "", tags: dict[str, str] | None = None
    ) -> SpanContext:
        """Returns a context manager that starts/ends a span automatically.

        Args:
            operation: Name of the traced operation.
            trace_id: Trace ID (auto-generated if empty).
            parent_span_id: Parent span ID for nesting.
            tags: Key-value tags to attach.

        Returns:
            A ``SpanContext`` context manager.
        """
        return SpanContext(self, operation, trace_id, parent_span_id, tags or {})


class SpanContext:
    """Context manager that starts a span on enter and ends it on exit."""

    def __init__(
        self, tracer: Tracer, operation: str, trace_id: str, parent_span_id: str, tags: dict[str, str]
    ) -> None:
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


class Console(SpanExporter):
    """Exports spans to stdout for development."""

    def export(self, spans: list[Span]) -> None:
        """Logs span details for development."""
        for span in spans:
            duration = span.end_ms - span.start_ms
            tag_str = " ".join(f"{k}={v}" for k, v in span.tags.items())
            err = f" ERROR={span.error}" if span.error else ""
            logger.info(
                "[trace] {} {}.{} {:.1f}ms parent={}{} {}",
                span.trace_id[:8],
                span.name,
                span.operation,
                duration,
                span.parent_span_id[:8],
                err,
                tag_str,
            )


class Otlp(SpanExporter):
    """Exports spans via OpenTelemetry OTLP.

    Initialises the SDK once at construction time so that each
    ``export()`` call reuses the same gRPC connection and avoids
    creating new providers/processors on every span batch.

    Requires the ``otlp`` extra (``opentelemetry-api``,
    ``opentelemetry-sdk``, ``opentelemetry-exporter-otlp``).
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:4317",
        service_name: str = "underwrite",
        insecure: bool = True,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.__endpoint = endpoint
        self.__service_name = service_name
        self.__insecure = insecure
        self.__headers = dict(headers) if headers else {}
        if endpoint.startswith("http://") and not insecure:
            raise ValueError(
                "endpoint uses plaintext http but insecure=False; "
                "either change the endpoint to https or pass insecure=True"
            )
        self.__provider: Any = None
        self.__tracer: Any = None
        self.__processor: Any = None

    def __lazy_init(self) -> bool:
        if self.__provider is not None:
            return True
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            logger.warning("OTLP exporter not available; install with: pip install underwrite[otlp]")
            return False

        resource = Resource.create({"service.name": self.__service_name})
        self.__provider = SdkTracerProvider(resource=resource)
        otlp_kwargs: dict[str, Any] = {"endpoint": self.__endpoint, "insecure": self.__insecure}
        if self.__headers:
            otlp_kwargs["headers"] = self.__headers
        otlp_exporter = OTLPSpanExporter(**otlp_kwargs)
        self.__processor = BatchSpanProcessor(otlp_exporter)
        self.__provider.add_span_processor(self.__processor)
        self.__tracer = self.__provider.get_tracer(__name__)
        return True

    def export(self, spans: list[Span]) -> None:
        if not self.__lazy_init():
            return

        for span in spans:
            sdk_span = self.__tracer.start_span(
                span.operation,
                attributes={
                    **span.tags,
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "service_id": span.name,
                    "duration_ms": f"{span.end_ms - span.start_ms:.1f}",
                },
            )
            if span.error:
                from opentelemetry import trace

                sdk_span.set_status(trace.Status(trace.StatusCode.ERROR, span.error))
            sdk_span.end()

        self.__processor.force_flush()
