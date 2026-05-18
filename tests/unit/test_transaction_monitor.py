"""Unit tests for real-time transaction monitoring rules engine."""

from __future__ import annotations

from ulu.anti_fraud.transaction_monitor import MonitoringRule, TransactionMonitor


class TestTransactionMonitor:
    def test_register_and_evaluate(self) -> None:
        monitor = TransactionMonitor()
        rule = MonitoringRule(
            rule_id="R1",
            name="high_amount",
            condition=lambda event: event.get("amount", 0) > 100000,
            severity="high",
            description="amount exceeds 100k",
        )
        monitor.register_rule(rule)
        alerts = monitor.evaluate({"event_type": "origination", "amount": 150000})
        assert len(alerts) == 1
        assert alerts[0].severity == "high"
        assert alerts[0].rule_id == "R1"

    def test_evaluate_no_match(self) -> None:
        monitor = TransactionMonitor()
        rule = MonitoringRule(
            rule_id="R1",
            name="high_amount",
            condition=lambda event: event.get("amount", 0) > 100000,
            severity="high",
            description="amount exceeds 100k",
        )
        monitor.register_rule(rule)
        alerts = monitor.evaluate({"event_type": "origination", "amount": 50000})
        assert len(alerts) == 0

    def test_multiple_rules(self) -> None:
        monitor = TransactionMonitor()
        monitor.register_rule(
            MonitoringRule(
                rule_id="R1", name="high_amount", condition=lambda e: e.get("amount", 0) > 100000,
                severity="high", description="amount > 100k",
            )
        )
        monitor.register_rule(
            MonitoringRule(
                rule_id="R2", name="rapid_origination", condition=lambda e: e.get("velocity", 0) > 5,
                severity="medium", description="velocity > 5",
            )
        )
        alerts = monitor.evaluate({"amount": 150000, "velocity": 10})
        assert len(alerts) == 2

    def test_list_alerts(self) -> None:
        monitor = TransactionMonitor()
        monitor.register_rule(
            MonitoringRule(
                rule_id="R1", name="high_amount", condition=lambda e: e.get("amount", 0) > 100000,
                severity="high", description="amount > 100k",
            )
        )
        monitor.evaluate({"amount": 150000})
        monitor.evaluate({"amount": 200000})
        assert len(monitor.list_alerts()) == 2
        assert len(monitor.list_alerts(severity="high")) == 2
        assert len(monitor.list_alerts(severity="low")) == 0

    def test_clear_alerts(self) -> None:
        monitor = TransactionMonitor()
        monitor.register_rule(
            MonitoringRule(
                rule_id="R1", name="high_amount", condition=lambda e: True,
                severity="high", description="always fires",
            )
        )
        monitor.evaluate({"amount": 1})
        monitor.clear_alerts()
        assert len(monitor.list_alerts()) == 0

    def test_summary(self) -> None:
        monitor = TransactionMonitor()
        monitor.register_rule(
            MonitoringRule(
                rule_id="R1", name="high", condition=lambda e: True,
                severity="high", description="always",
            )
        )
        monitor.register_rule(
            MonitoringRule(
                rule_id="R2", name="low", condition=lambda e: True,
                severity="low", description="always",
            )
        )
        monitor.evaluate({})
        summary = monitor.summary()
        assert summary["high"] == 1
        assert summary["low"] == 1

    def test_rule_exception_caught(self) -> None:
        monitor = TransactionMonitor()
        monitor.register_rule(
            MonitoringRule(
                rule_id="R1", name="broken", condition=lambda e: 1 / 0,
                severity="high", description="always raises",
            )
        )
        alerts = monitor.evaluate({"amount": 1})
        assert len(alerts) == 0
