"""Prometheus-style alerting rule engine for operational metrics.

Item 58 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime
from collections.abc import Callable

from ulu.infra.logging import logger


@dataclasses.dataclass
class AlertRule:
    """A threshold-based alerting rule."""

    name: str
    metric: str
    operator: str  # "gt", "lt", "eq", "ge", "le"
    threshold: float
    severity: str  # "warning", "critical"
    description: str


@dataclasses.dataclass
class FiredAlert:
    """An alert instance generated when a rule threshold is breached."""

    rule_name: str
    severity: str
    message: str
    value: float
    threshold: float
    fired_at: datetime.datetime


class AlertingEngine:
    """Evaluates alert rules against a metrics snapshot."""

    _OPERATORS: dict[str, Callable[[float, float], bool]] = {
        "gt": lambda v, t: v > t,
        "lt": lambda v, t: v < t,
        "eq": lambda v, t: v == t,
        "ge": lambda v, t: v >= t,
        "le": lambda v, t: v <= t,
    }

    def __init__(self) -> None:
        self._rules: list[AlertRule] = []
        self._alerts: list[FiredAlert] = []

    def register(self, rule: AlertRule) -> None:
        self._rules.append(rule)
        logger.info("alert_rule_registered", name=rule.name, metric=rule.metric)

    def evaluate(self, metrics: dict[str, float]) -> list[FiredAlert]:
        """Evaluates all rules against the provided metrics snapshot."""
        fired: list[FiredAlert] = []
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for rule in self._rules:
            value = metrics.get(rule.metric)
            if value is None:
                continue
            op = self._OPERATORS.get(rule.operator)
            if op is None:
                continue
            if op(value, rule.threshold):
                alert = FiredAlert(
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"{rule.description} (value={value}, threshold={rule.threshold})",
                    value=value,
                    threshold=rule.threshold,
                    fired_at=now,
                )
                self._alerts.append(alert)
                fired.append(alert)
                logger.warning(
                    "alert_fired",
                    rule=rule.name,
                    severity=rule.severity,
                    metric=rule.metric,
                    value=value,
                    threshold=rule.threshold,
                )
        return fired

    def list_alerts(
        self,
        severity: str | None = None,
        since: datetime.datetime | None = None,
    ) -> list[FiredAlert]:
        results = list(self._alerts)
        if severity:
            results = [a for a in results if a.severity == severity]
        if since:
            results = [a for a in results if a.fired_at >= since]
        return results

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for alert in self._alerts:
            counts[alert.severity] = counts.get(alert.severity, 0) + 1
        return counts

    def clear(self) -> None:
        self._alerts.clear()
