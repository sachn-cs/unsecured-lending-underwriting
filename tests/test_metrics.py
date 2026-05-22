"""Tests for MetricsCollector."""

from __future__ import annotations

from underwrite.__metrics__ import MetricsCollector


class TestMetricsCollector:

    def test_counter_default_zero(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot()
        assert len(snap["counters"]) == 0

    def test_counter_increment(self) -> None:
        mc = MetricsCollector()
        mc.increment("reqs")
        mc.increment("reqs", delta=3)
        snap = mc.snapshot()
        assert snap["counters"]["reqs"]["value"] == 4

    def test_counter_with_tags(self) -> None:
        mc = MetricsCollector()
        mc.increment("reqs", {"service": "risk"})
        snap = mc.snapshot()
        assert any(c["value"] == 1 for c in snap["counters"].values())

    def test_gauge(self) -> None:
        mc = MetricsCollector()
        mc.gauge("mem", 42.5)
        snap = mc.snapshot()
        assert any(g["value"] == 42.5 for g in snap["gauges"].values())

    def test_timer(self) -> None:
        mc = MetricsCollector()
        mc.timer("handle", 10.0)
        mc.timer("handle", 20.0)
        snap = mc.snapshot()
        timer = snap["timers"]["handle"]
        assert timer["count"] == 2
        assert timer["avg_ms"] == 15.0
        assert timer["min_ms"] == 10.0
        assert timer["max_ms"] == 20.0

    def test_timer_context(self) -> None:
        mc = MetricsCollector()
        with mc.time("ctx"):
            pass
        snap = mc.snapshot()
        assert snap["timers"]["ctx"]["count"] == 1

    def test_reset(self) -> None:
        mc = MetricsCollector()
        mc.increment("x")
        mc.reset()
        snap = mc.snapshot()
        assert len(snap["counters"]) == 0

    def test_evicts_when_max_metrics_exceeded(self) -> None:
        mc = MetricsCollector(max_metrics=6)
        for i in range(10):
            mc.increment(f"counter_{i}")
        snap = mc.snapshot()
        assert len(snap["counters"]) <= 6

    def test_no_eviction_below_max(self) -> None:
        mc = MetricsCollector(max_metrics=100)
        for i in range(5):
            mc.increment(f"counter_{i}")
        snap = mc.snapshot()
        assert len(snap["counters"]) == 5

    def test_evicts_timers_when_max_exceeded(self) -> None:
        mc = MetricsCollector(max_metrics=3)
        for i in range(10):
            mc.timer(f"timer_{i}", 1.0)
        snap = mc.snapshot()
        # At least some eviction happened
        assert len(snap["timers"]) <= 3

    def test_evicts_gauges_when_max_exceeded(self) -> None:
        mc = MetricsCollector(max_metrics=3)
        for i in range(10):
            mc.gauge(f"gauge_{i}", float(i))
        snap = mc.snapshot()
        assert len(snap["gauges"]) <= 3
