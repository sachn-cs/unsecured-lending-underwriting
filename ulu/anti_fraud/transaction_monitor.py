"""Real-time transaction monitoring rules engine for fraud detection.

Item 43 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime
from collections.abc import Callable
from typing import Any

from ulu.infra.logging import logger


@dataclasses.dataclass
class MonitoringRule:
    """A configurable rule for transaction monitoring."""

    rule_id: str
    name: str
    condition: Callable[[dict[str, Any]], bool]
    severity: str  # "low", "medium", "high", "critical"
    description: str


@dataclasses.dataclass
class Alert:
    """An alert fired by the monitoring engine."""

    alert_id: str
    rule_id: str
    severity: str
    message: str
    context: dict[str, Any]
    fired_at: datetime.datetime


class TransactionMonitor:
    """Streams events through fraud detection rules with configurable thresholds."""

    def __init__(self) -> None:
        self._rules: list[MonitoringRule] = []
        self._alerts: list[Alert] = []

    def register_rule(self, rule: MonitoringRule) -> None:
        self._rules.append(rule)
        logger.info("monitoring_rule_registered", rule_id=rule.rule_id, name=rule.name)

    def evaluate(self, event: dict[str, Any]) -> list[Alert]:
        """Evaluates a single event against all registered rules."""
        fired: list[Alert] = []
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for rule in self._rules:
            try:
                if rule.condition(event):
                    alert = Alert(
                        alert_id=f"alert-{rule.rule_id}-{now.isoformat()}",
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=f"Rule '{rule.name}' triggered: {rule.description}",
                        context=dict(event),
                        fired_at=now,
                    )
                    self._alerts.append(alert)
                    fired.append(alert)
                    logger.warning(
                        "monitoring_alert_fired",
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        event_type=event.get("event_type"),
                    )
            except Exception as exc:
                logger.error("monitoring_rule_error", rule_id=rule.rule_id, error=str(exc))
        return fired

    def list_alerts(
        self,
        severity: str | None = None,
        since: datetime.datetime | None = None,
    ) -> list[Alert]:
        results = list(self._alerts)
        if severity:
            results = [a for a in results if a.severity == severity]
        if since:
            results = [a for a in results if a.fired_at >= since]
        return results

    def clear_alerts(self) -> None:
        self._alerts.clear()

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for alert in self._alerts:
            counts[alert.severity] = counts.get(alert.severity, 0) + 1
        return counts
