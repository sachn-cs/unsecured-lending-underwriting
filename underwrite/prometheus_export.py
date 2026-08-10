"""Prometheus text-format export for underwrite Collector.

Usage:
    exporter = Exporter()
    text = exporter.to_prometheus_text(runtime)
"""

from __future__ import annotations

__all__ = [
    "Exporter",
    "PrometheusMiddleware",
    "metrics_as_text",
]

from typing import Any

from underwrite.pii import PIISanitizer

_redactor = PIISanitizer()


def _redact_tag_value(value: str) -> str:
    """Redacts PII patterns inside a Prometheus tag value.

    Metric tag values are persisted by Prometheus for the configured
    retention period and are visible to anyone with access to the
    scrape endpoint. A user-controlled tag (e.g. ``loan_id``,
    ``customer_id``) must not carry PII patterns.
    """
    return PIISanitizer.redact_str(str(value))


class Exporter:
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
            safe = Exporter.__sanitize(name)
            tags = Exporter.__format_tags(data.get("tags", {}))
            lines.append(f"# HELP {safe} Counter metric")
            lines.append(f"# TYPE {safe} counter")
            lines.append(f"{safe}{{{tags}}} {data['value']}")

        for name, data in snap.get("gauges", {}).items():
            safe = Exporter.__sanitize(name)
            tags = Exporter.__format_tags(data.get("tags", {}))
            lines.append(f"# HELP {safe} Gauge metric")
            lines.append(f"# TYPE {safe} gauge")
            lines.append(f"{safe}{{{tags}}} {data['value']}")

        for name, data in snap.get("timers", {}).items():
            safe = Exporter.__sanitize(name)
            tags = Exporter.__format_tags(data.get("tags", {}))
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
            safe_k = Exporter.__sanitize(str(k))
            safe_v = _redact_tag_value(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
            parts.append(f'{safe_k}="{safe_v}"')
        return ",".join(parts)


_exporter = Exporter()


def metrics_as_text(runtime: Any) -> str:
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
