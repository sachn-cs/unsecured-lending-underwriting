"""Unit tests for alerting engine."""

from __future__ import annotations

import datetime

from ulu.infra.alerting import AlertingEngine, AlertRule


class TestAlertingEngine:
    def test_evaluate_no_rules(self) -> None:
        engine = AlertingEngine()
        assert engine.evaluate({"cpu": 90.0}) == []

    def test_evaluate_threshold_breach(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("high_cpu", "cpu", "gt", 80.0, "warning", "CPU above 80%"))
        fired = engine.evaluate({"cpu": 90.0})
        assert len(fired) == 1
        assert fired[0].rule_name == "high_cpu"
        assert fired[0].severity == "warning"
        assert fired[0].value == 90.0

    def test_evaluate_no_breach(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("high_cpu", "cpu", "gt", 80.0, "warning", "CPU above 80%"))
        fired = engine.evaluate({"cpu": 50.0})
        assert fired == []

    def test_evaluate_missing_metric(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("high_cpu", "cpu", "gt", 80.0, "warning", "CPU above 80%"))
        fired = engine.evaluate({"memory": 90.0})
        assert fired == []

    def test_operators(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("eq", "x", "eq", 5.0, "critical", "x must be 5"))
        engine.register(AlertRule("le", "y", "le", 10.0, "warning", "y must be <= 10"))
        engine.register(AlertRule("ge", "z", "ge", 20.0, "warning", "z must be >= 20"))
        fired = engine.evaluate({"x": 5.0, "y": 9.0, "z": 20.0})
        assert len(fired) == 3

    def test_summary(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("r1", "m", "gt", 0.0, "critical", "desc"))
        engine.evaluate({"m": 1.0})
        assert engine.summary() == {"critical": 1}

    def test_clear(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("r1", "m", "gt", 0.0, "warning", "desc"))
        engine.evaluate({"m": 1.0})
        assert len(engine.list_alerts()) == 1
        engine.clear()
        assert engine.list_alerts() == []

    def test_list_alerts_by_severity(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("r1", "m", "gt", 0.0, "warning", "desc"))
        engine.register(AlertRule("r2", "m", "gt", 0.0, "critical", "desc"))
        engine.evaluate({"m": 1.0})
        assert len(engine.list_alerts(severity="warning")) == 1
        assert len(engine.list_alerts(severity="critical")) == 1

    def test_list_alerts_since(self) -> None:
        engine = AlertingEngine()
        engine.register(AlertRule("r1", "m", "gt", 0.0, "warning", "desc"))
        engine.evaluate({"m": 1.0})
        since = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(minutes=1)
        assert len(engine.list_alerts(since=since)) == 1
        since = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(minutes=1)
        assert len(engine.list_alerts(since=since)) == 0
