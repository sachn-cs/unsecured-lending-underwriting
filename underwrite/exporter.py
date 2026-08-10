"""Periodic metrics export loop.

Lifecycle helper that runs a background thread snapshotting a
Collector at a configurable interval. Extracted from
Runtime so the composition root does not own thread management
and snapshotting logic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from underwrite.logger import logger
from underwrite.metrics import Collector
from underwrite.pii import PIISanitizer


class Exporter:
    """Periodically snapshots a Collector on a background thread.

    start() launches a daemon thread that calls snapshot() every
    *interval_seconds* and forwards the result to *on_snapshot*.
    stop() signals the thread to exit and joins it with a bounded
    timeout.

    Snapshots are forwarded via a callback (rather than a
    push-channel) so the exporter has no opinion about where the
    snapshot goes — Runtime can pipe to Prometheus, OTLP, or a
    log file by changing only the callback.
    """

    def __init__(
        self,
        metrics: Collector,
        interval_seconds: float,
        on_snapshot: Callable[[dict], None] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self.__metrics: Collector = metrics
        self.__interval_seconds: float = interval_seconds
        self.__on_snapshot: Callable[[dict], None] | None = on_snapshot
        self.__stop_event: threading.Event = threading.Event()
        self.__thread: threading.Thread | None = None

    def start(self) -> None:
        if self.__thread is not None:
            return
        self.__stop_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run, daemon=True, name="metrics-exporter")
        self.__thread.start()

    def __run(self) -> None:
        while not self.__stop_event.is_set():
            self.__stop_event.wait(self.__interval_seconds)
            if self.__stop_event.is_set():
                break
            try:
                snap = self.__metrics.snapshot()
                if self.__on_snapshot is not None:
                    self.__on_snapshot(snap)
            except (OSError, ValueError, TypeError) as exc:
                logger.exception("metrics snapshot failed: {}", exc)

    def stop(self, timeout: float = 5.0) -> None:
        self.__stop_event.set()
        if self.__thread is not None:
            self.__thread.join(timeout=timeout)
            self.__thread = None


_redactor = PIISanitizer()


def _redact_tag_value(value: str) -> str:
    """Redacts PII patterns inside a Prometheus tag value.

    Metric tag values are persisted by Prometheus for the configured
    retention period and are visible to anyone with access to the
    scrape endpoint. A user-controlled tag (e.g. ``loan_id``,
    ``customer_id``) must not carry PII patterns.
    """
    return PIISanitizer.redact_str(str(value))


class Prometheus:
    """Formats runtime metrics into Prometheus exposition text format.

    Serialises counters, gauges, and timers from the Runtime's
    ``Collector`` snapshot into the Prometheus text format
    with ``TYPE`` and ``HELP`` headers.
    """

    @staticmethod
    def to_prometheus_text(runtime: Any) -> str:
        """Serialise the Runtime's metrics snapshot as Prometheus exposition text.

        Args:
            runtime: An underwrite Runtime instance with a ``metrics`` property.

        Returns:
            Prometheus-format text with TYPE/HELP headers for counters,
            gauges, and timers.
        """
        mc = runtime.metrics
        if mc is None:
            return ""
        snap = mc.snapshot()
        lines: list[str] = []

        for name, data in snap.get("counters", {}).items():
            safe = Prometheus.__sanitize(name)
            tags = Prometheus.__format_tags(data.get("tags", {}))
            lines.append(f"# HELP {safe} Counter metric")
            lines.append(f"# TYPE {safe} counter")
            lines.append(f"{safe}{{{tags}}} {data['value']}")

        for name, data in snap.get("gauges", {}).items():
            safe = Prometheus.__sanitize(name)
            tags = Prometheus.__format_tags(data.get("tags", {}))
            lines.append(f"# HELP {safe} Gauge metric")
            lines.append(f"# TYPE {safe} gauge")
            lines.append(f"{safe}{{{tags}}} {data['value']}")

        for name, data in snap.get("timers", {}).items():
            safe = Prometheus.__sanitize(name)
            tags = Prometheus.__format_tags(data.get("tags", {}))
            lines.append(f"# HELP {safe} Timer metric")
            lines.append(f"# TYPE {safe} gauge")
            lines.append(f"{safe}_count{{{tags}}} {data['count']}")
            lines.append(f"{safe}_avg_ms{{{tags}}} {data['avg_ms']}")
            lines.append(f"{safe}_min_ms{{{tags}}} {data['min_ms']}")
            lines.append(f"{safe}_max_ms{{{tags}}} {data['max_ms']}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def __sanitize(name: str) -> str:
        """Replace non-Prometheus-safe characters in metric names."""
        return name.replace(":", "_").replace(".", "_").replace("-", "_")

    @staticmethod
    def __format_tags(tags: dict[str, str]) -> str:
        """Format a dict of tags as a Prometheus label string.

        Escapes backslashes, double-quotes, and newlines so a
        user-controlled tag value (e.g. a service id) cannot break
        out of the label string and inject arbitrary exposition
        content. Also redacts PII patterns inside tag values so a
        misconfigured caller cannot persist PAN/Aadhaar/mobile
        numbers into the Prometheus TSDB.
        """
        parts: list[str] = []
        for k, v in sorted(tags.items()):
            safe_k = Prometheus.__sanitize(str(k))
            safe_v = _redact_tag_value(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
            parts.append(f'{safe_k}="{safe_v}"')
        return ",".join(parts)


_exporter = Prometheus()


def prometheus_text(runtime: Any) -> str:
    return _exporter.to_prometheus_text(runtime)


class PrometheusMiddleware:
    """Starlette/FastAPI middleware that exposes Prometheus metrics.

    Attaches a ``/metrics-prometheus`` endpoint that returns the
    underwrite Runtime's internal metrics in Prometheus text format.

    Authentication mirrors the ``/v1/publish`` token: a
    ``UNDERWRITE_API_TOKEN`` value (or the ``api_token`` constructor
    arg) must be configured and the request must carry
    ``Authorization: Bearer <token>``. Operators are expected to
    keep the metrics endpoint on a private network; the token is
    a defence-in-depth check, not a substitute for network
    isolation.
    """

    def __init__(self, app: Any, runtime: Any, api_token: str | None = None) -> None:
        self.app = app
        self.runtime = runtime
        import os

        self.__api_token: str = api_token or os.environ.get("UNDERWRITE_API_TOKEN", "") or ""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") == "/metrics-prometheus":
            from fastapi.responses import JSONResponse, PlainTextResponse, Response

            response: Response
            if self.__api_token:
                import hmac

                headers = scope.get("headers") or []
                auth = ""
                for header in headers:
                    if len(header) < 2:
                        continue
                    k, v = header[0], header[1]
                    if k == b"authorization" or k == "authorization":
                        try:
                            auth = v.decode("latin-1") if isinstance(v, bytes) else str(v)
                        except (UnicodeDecodeError, AttributeError, TypeError):
                            auth = ""
                        break
                expected = f"Bearer {self.__api_token}"
                if not hmac.compare_digest(auth, expected):
                    response = JSONResponse(
                        {"error": "unauthorized"},
                        status_code=401,
                    )
                    await response(scope, receive, send)
                    return
            text = _exporter.to_prometheus_text(self.runtime)
            response = PlainTextResponse(text, media_type="text/plain; version=0.0.4")
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def prometheus_text(runtime: Any) -> str:
    return _exporter.to_prometheus_text(runtime)
