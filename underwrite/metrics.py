# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Thread-safe metrics collector — counters, timers, gauges."""

from __future__ import annotations

__all__ = [
    "Collector",
    "Counter",
    "Gauge",
    "MetricsSink",
    "Timer",
    "TimerContext",
]

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class MetricsSink(Protocol):
    """Minimal interface for emitting a metric increment.

    Any object with an ``increment`` method satisfies this protocol,
    enabling dependency-inverted wiring of optional metrics
    collectors without coupling to :class:`Collector`.
    """

    def increment(self, name: str, tags: dict[str, str] | None = None, delta: int = 1) -> None: ...


class Clock(Protocol):
    """Time source abstraction for dependency inversion.

    Services and infrastructure code depend on this Protocol rather
    than calling ``time.time()`` / ``datetime.now()`` directly. Tests
    inject a deterministic clock to avoid flaky timing assertions
    and to control the visible timestamp of emitted events.
    """

    def now(self) -> float:
        """Returns monotonic seconds since an arbitrary epoch."""

    def iso(self) -> str:
        """Returns an ISO-8601 UTC timestamp string."""

    def utc_now(self) -> Any:
        """Returns the current UTC ``datetime`` for callers that need
        timedelta arithmetic on a wall-clock value."""


class SystemClock:
    """Default Clock backed by the system wall-clock.

    Real production wiring uses this. Tests should inject a
    ``FakeClock`` (or similar) to make time-dependent behaviour
    deterministic.
    """

    def now(self) -> float:
        return time.time()

    def iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def utc_now(self) -> Any:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)


@dataclass(slots=True)
class Counter:
    """A monotonically increasing counter metric."""

    name: str
    tags: dict[str, str] = field(default_factory=dict)
    value: int = 0


@dataclass(slots=True)
class Gauge:
    """A gauge metric that records a point-in-time value."""

    name: str
    tags: dict[str, str] = field(default_factory=dict)
    value: float = 0.0


@dataclass(slots=True)
class Timer:
    """A timer metric that tracks duration statistics (count, total, min, max)."""

    name: str
    tags: dict[str, str] = field(default_factory=dict)
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0


class Collector:
    """Thread-safe in-memory metrics collector.

    Evicts oldest entries when *max_metrics* is exceeded to prevent
    unbounded memory growth.
    """

    def __init__(self, max_metrics: int = 10000) -> None:
        """Initializes an empty metrics collector.

        Args:
            max_metrics: Maximum metric entries before eviction.
        """
        self.lock: threading.Lock = threading.Lock()
        self.counters: dict[str, Counter] = {}
        self.timers: dict[str, Timer] = {}
        self.gauges: dict[str, Gauge] = {}
        self.max_metrics: int = max_metrics

    def evict(self) -> None:
        total = len(self.counters) + len(self.timers) + len(self.gauges)
        if total <= self.max_metrics:
            return
        target = self.max_metrics // 3
        for metric_map in (self.counters, self.timers, self.gauges):
            excess = len(metric_map) - target
            if excess <= 0:
                continue
            for key in list(metric_map)[:excess]:
                del metric_map[key]

    def key(self, name: str, tags: dict[str, str]) -> str:
        parts = [name]
        for k, v in sorted(tags.items()):
            parts.append(f"{k}={v}")
        return ":".join(parts)

    def increment(self, name: str, tags: dict[str, str] | None = None, delta: int = 1) -> None:
        """Increments a counter metric.

        Args:
            name: Metric name.
            tags: Optional key-value tags.
            delta: Amount to increment (default 1).
        """
        tags = tags or {}
        key = self.key(name, tags)
        with self.lock:
            if key not in self.counters:
                self.counters[key] = Counter(name=name, tags=dict(tags))
            self.counters[key].value += delta
            self.evict()

    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Sets a gauge metric to a specific value.

        Args:
            name: Metric name.
            value: Current value.
            tags: Optional key-value tags.
        """
        tags = tags or {}
        key = self.key(name, tags)
        with self.lock:
            self.gauges[key] = Gauge(name=name, tags=dict(tags), value=value)
            self.evict()

    def timer(self, name: str, duration_ms: float, tags: dict[str, str] | None = None) -> None:
        """Records a timer observation.

        Args:
            name: Metric name.
            duration_ms: Observed duration in milliseconds.
            tags: Optional key-value tags.
        """
        tags = tags or {}
        key = self.key(name, tags)
        with self.lock:
            if key not in self.timers:
                self.timers[key] = Timer(name=name, tags=dict(tags))
            t = self.timers[key]
            t.count += 1
            t.total_ms += duration_ms
            if duration_ms < t.min_ms:
                t.min_ms = duration_ms
            if duration_ms > t.max_ms:
                t.max_ms = duration_ms
            self.evict()

    def time(self, name: str, tags: dict[str, str] | None = None) -> TimerContext:
        """Returns a context manager that records duration on exit.

        Args:
            name: Metric name.
            tags: Optional key-value tags.

        Returns:
            A ``TimerContext`` for use in a ``with`` block.
        """
        return TimerContext(self, name, tags or {})

    def snapshot(self) -> dict[str, Any]:
        """Returns a point-in-time copy of all metrics.

        Returns:
            Dict with ``"counters"``, ``"timers"``, and ``"gauges"`` keys.
        """
        with self.lock:
            return {
                "counters": {k: {"value": c.value, "tags": c.tags} for k, c in self.counters.items()},
                "timers": {
                    k: {
                        "count": t.count,
                        "avg_ms": t.total_ms / max(t.count, 1),
                        "min_ms": t.min_ms if t.count else 0,
                        "max_ms": t.max_ms,
                        "tags": t.tags,
                    }
                    for k, t in self.timers.items()
                },
                "gauges": {k: {"value": g.value, "tags": g.tags} for k, g in self.gauges.items()},
            }

    def reset(self) -> None:
        """Clears all counters, timers, and gauges."""
        with self.lock:
            self.counters.clear()
            self.timers.clear()
            self.gauges.clear()


class TimerContext:
    """Context manager that records elapsed time to a Collector."""

    def __init__(self, collector: Collector, name: str, tags: dict[str, str]) -> None:
        self.collector = collector
        self.name = name
        self.tags = tags
        self.start: float = 0.0

    def __enter__(self) -> TimerContext:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        elapsed = (time.perf_counter() - self.start) * 1000.0
        self.collector.timer(self.name, elapsed, self.tags)
