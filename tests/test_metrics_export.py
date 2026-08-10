# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Prometheus prometheus text formatting."""

from __future__ import annotations

from unittest.mock import MagicMock

from underwrite.exporter import Prometheus, PrometheusMiddleware


def _mock_runtime(snapshot: dict) -> MagicMock:
    rt = MagicMock()
    mc = MagicMock()
    mc.snapshot.return_value = snapshot
    rt.metrics = mc
    return rt


class TestMetricsExporter:
    def test_empty_metrics_returns_trailing_newline(self) -> None:
        rt = _mock_runtime({})
        text = Prometheus.to_prometheus_text(rt)
        assert text == "\n"

    def test_no_metrics_collector(self) -> None:
        rt = MagicMock()
        rt.metrics = None
        text = Prometheus.to_prometheus_text(rt)
        assert text == ""

    def test_counter_output_format(self) -> None:
        snap = {"counters": {"events.handled": {"value": 42, "tags": {"service": "test"}}}}
        rt = _mock_runtime(snap)
        text = Prometheus.to_prometheus_text(rt)
        assert "# HELP events_handled Counter metric" in text
        assert "# TYPE events_handled counter" in text
        assert 'events_handled{service="test"} 42' in text

    def test_gauge_output_format(self) -> None:
        snap = {"gauges": {"active.loans": {"value": 10, "tags": {"type": "unsecured"}}}}
        rt = _mock_runtime(snap)
        text = Prometheus.to_prometheus_text(rt)
        assert "# HELP active_loans Gauge metric" in text
        assert "# TYPE active_loans gauge" in text
        assert 'active_loans{type="unsecured"} 10' in text

    def test_timer_output_format(self) -> None:
        snap = {
            "timers": {
                "handle.duration": {
                    "count": 5,
                    "avg_ms": 10.0,
                    "min_ms": 2.0,
                    "max_ms": 25.0,
                    "tags": {"service": "test"},
                }
            }
        }
        rt = _mock_runtime(snap)
        text = Prometheus.to_prometheus_text(rt)
        assert "# TYPE handle_duration gauge" in text
        assert 'handle_duration_count{service="test"} 5' in text
        assert 'handle_duration_avg_ms{service="test"} 10.0' in text
        assert 'handle_duration_min_ms{service="test"} 2.0' in text
        assert 'handle_duration_max_ms{service="test"} 25.0' in text


class TestPrometheusMiddlewareAuth:
    @staticmethod
    async def _run(mw, headers: list[tuple[bytes, bytes]]):
        scope = {
            "type": "http",
            "path": "/metrics-prometheus",
            "method": "GET",
            "headers": headers,
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        await mw(scope, await receive(), send)
        return sent

    def test_unauthorized_without_bearer(self) -> None:
        import asyncio

        mw = PrometheusMiddleware(MagicMock(), MagicMock(), api_token="secret")
        sent = asyncio.run(self._run(mw, []))
        assert any(m.get("status") == 401 for m in sent), sent

    def test_authorized_with_correct_bearer(self) -> None:
        import asyncio

        mw = PrometheusMiddleware(MagicMock(), MagicMock(), api_token="secret")
        sent = asyncio.run(self._run(mw, [(b"authorization", b"Bearer secret")]))
        assert any(m.get("status") == 200 for m in sent), sent

    def test_rejects_wrong_bearer(self) -> None:
        import asyncio

        mw = PrometheusMiddleware(MagicMock(), MagicMock(), api_token="secret")
        sent = asyncio.run(self._run(mw, [(b"authorization", b"Bearer wrong")]))
        assert any(m.get("status") == 401 for m in sent), sent

    def test_open_when_no_token_configured(self) -> None:
        """No token configured means the endpoint is open; operators
        are expected to keep the metrics endpoint on a private
        network."""
        import asyncio

        mw = PrometheusMiddleware(MagicMock(), MagicMock())
        sent = asyncio.run(self._run(mw, []))
        assert any(m.get("status") == 200 for m in sent), sent
