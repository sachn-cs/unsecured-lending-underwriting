"""Thread-safe metrics collector — counters, timers, gauges."""

from __future__ import annotations

__all__ = [
    "Counter",
    "Gauge",
    "MetricsCollector",
    "Timer",
    "TimerContext",
]

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Counter:
    """A monotonically increasing counter metric."""

    name: str
    tags: dict[str, str] = field(default_factory=dict)
    value: int = 0


@dataclass
class Gauge:
    """A gauge metric that records a point-in-time value."""

    name: str
    tags: dict[str, str] = field(default_factory=dict)
    value: float = 0.0


@dataclass
class Timer:
    """A timer metric that tracks duration statistics (count, total, min, max)."""

    name: str
    tags: dict[str, str] = field(default_factory=dict)
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0


class MetricsCollector:
    """Thread-safe in-memory metrics collector.

    Evicts oldest entries when *max_metrics* is exceeded to prevent
    unbounded memory growth.
    """

    def __init__(self, max_metrics: int = 10000) -> None:
        """Initialises an empty metrics collector.

        Args:
            max_metrics: Maximum metric entries before eviction.
        """
        self.__lock: threading.Lock = threading.Lock()
        self.__counters: dict[str, Counter] = {}
        self.__timers: dict[str, Timer] = {}
        self.__gauges: dict[str, Gauge] = {}
        self.__max_metrics: int = max_metrics

    def __evict(self) -> None:
        total = len(self.__counters) + len(self.__timers) + len(self.__gauges)
        if total <= self.__max_metrics:
            return
        target = self.__max_metrics // 3
        for metric_map in (self.__counters, self.__timers, self.__gauges):
            excess = len(metric_map) - target
            if excess <= 0:
                continue
            for _ in range(excess):
                try:
                    metric_map.pop(next(iter(metric_map)))
                except KeyError:
                    break

    def __key(self, name: str, tags: dict[str, str]) -> str:
        parts = [name]
        for k, v in sorted(tags.items()):
            parts.append(f"{k}={v}")
        return ":".join(parts)

    def increment(self,
                  name: str,
                  tags: dict[str, str] | None = None,
                  delta: int = 1) -> None:
        """Increments a counter metric.

        Args:
            name: Metric name.
            tags: Optional key-value tags.
            delta: Amount to increment (default 1).
        """
        tags = tags or {}
        key = self.__key(name, tags)
        with self.__lock:
            if key not in self.__counters:
                self.__counters[key] = Counter(name=name, tags=dict(tags))
            self.__counters[key].value += delta
            self.__evict()

    def gauge(self,
              name: str,
              value: float,
              tags: dict[str, str] | None = None) -> None:
        """Sets a gauge metric to a specific value.

        Args:
            name: Metric name.
            value: Current value.
            tags: Optional key-value tags.
        """
        tags = tags or {}
        key = self.__key(name, tags)
        with self.__lock:
            self.__gauges[key] = Gauge(name=name, tags=dict(tags), value=value)
            self.__evict()

    def timer(self,
              name: str,
              duration_ms: float,
              tags: dict[str, str] | None = None) -> None:
        """Records a timer observation.

        Args:
            name: Metric name.
            duration_ms: Observed duration in milliseconds.
            tags: Optional key-value tags.
        """
        tags = tags or {}
        key = self.__key(name, tags)
        with self.__lock:
            if key not in self.__timers:
                self.__timers[key] = Timer(name=name, tags=dict(tags))
            t = self.__timers[key]
            t.count += 1
            t.total_ms += duration_ms
            if duration_ms < t.min_ms:
                t.min_ms = duration_ms
            if duration_ms > t.max_ms:
                t.max_ms = duration_ms
            self.__evict()

    def time(self,
             name: str,
             tags: dict[str, str] | None = None) -> TimerContext:
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
        with self.__lock:
            return {
                "counters": {
                    k: {
                        "value": c.value,
                        "tags": c.tags
                    } for k, c in self.__counters.items()
                },
                "timers": {
                    k: {
                        "count": t.count,
                        "avg_ms": t.total_ms / max(t.count, 1),
                        "min_ms": t.min_ms if t.count else 0,
                        "max_ms": t.max_ms,
                        "tags": t.tags
                    } for k, t in self.__timers.items()
                },
                "gauges": {
                    k: {
                        "value": g.value,
                        "tags": g.tags
                    } for k, g in self.__gauges.items()
                },
            }

    def reset(self) -> None:
        """Clears all counters, timers, and gauges."""
        with self.__lock:
            self.__counters.clear()
            self.__timers.clear()
            self.__gauges.clear()


class TimerContext:
    """Context manager that records elapsed time to a MetricsCollector."""

    def __init__(self, collector: MetricsCollector, name: str,
                 tags: dict[str, str]) -> None:
        self.__collector = collector
        self.__name = name
        self.__tags = tags
        self.__start: float = 0.0

    def __enter__(self) -> TimerContext:
        self.__start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        elapsed = (time.perf_counter() - self.__start) * 1000.0
        self.__collector.timer(self.__name, elapsed, self.__tags)
