"""OpenTelemetry-compatible tracing stub with span context managers.

Item 55 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from ulu.infra.logging import logger


@dataclasses.dataclass
class Span:
    """Represents a single trace span."""

    span_id: str
    name: str
    start_time: float
    end_time: float | None = None
    attributes: dict[str, Any] = dataclasses.field(default_factory=dict)
    events: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def end(self) -> None:
        self.end_time = time.time()

    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000.0


class Tracer:
    """Simple tracer producing spans for local development.

    Production replaces this with opentelemetry.sdk.trace.TracerProvider.
    """

    def __init__(self, tracer_name: str = "ulu") -> None:
        self.tracer_name = tracer_name
        self.spans: list[Span] = []

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        span = Span(
            span_id=str(uuid.uuid4()),
            name=name,
            start_time=time.time(),
            attributes=dict(attributes) if attributes else {},
        )
        self.spans.append(span)
        logger.debug("span_started", span_name=name, tracer=self.tracer_name)
        return span

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Generator[Span, None, None]:
        s = self.start_span(name, attributes)
        try:
            yield s
        finally:
            s.end()
            logger.debug("span_ended", span_name=name, duration_ms=s.duration_ms())


class NoOpTracer(Tracer):
    """Tracer that records nothing. Used when telemetry is disabled."""

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        return Span(span_id="", name=name, start_time=time.time())

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Generator[Span, None, None]:
        yield self.start_span(name, attributes)
