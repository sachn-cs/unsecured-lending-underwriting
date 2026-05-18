"""Rule-based early warning system for default prediction.

Item 42 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ulu.infra.logging import logger


@dataclass
class RiskSignal:
    """A single risk indicator with severity and context."""

    signal_type: str
    severity: str  # "low", "medium", "high", "critical"
    description: str
    metric_value: float
    threshold: float


class EarlyWarningService:
    """Evaluates behavioral signals and emits risk alerts.

    Uses simple rule-based thresholds rather than ML to avoid cold-start
    problems and keep explainability for RBI compliance.
    """

    def __init__(
        self,
        payment_delay_threshold_days: float = 3.0,
        cash_flow_drop_threshold: float = 0.30,
        bounce_event_threshold: int = 2,
        utilization_spike_threshold: float = 0.20,
    ) -> None:
        self.payment_delay_threshold = payment_delay_threshold_days
        self.cash_flow_drop_threshold = cash_flow_drop_threshold
        self.bounce_event_threshold = bounce_event_threshold
        self.utilization_spike_threshold = utilization_spike_threshold

    def evaluate_payment_delay(self, days_overdue: float) -> RiskSignal | None:
        """Flags borrowers with overdue payments beyond threshold."""
        if days_overdue <= 0:
            return None
        severity = "medium" if days_overdue <= self.payment_delay_threshold else "high"
        return RiskSignal(
            signal_type="payment_delay",
            severity=severity,
            description=f"payment overdue by {days_overdue:.1f} days",
            metric_value=days_overdue,
            threshold=self.payment_delay_threshold,
        )

    def evaluate_cash_flow_drop(
        self,
        current_monthly_inflow: float,
        avg_monthly_inflow: float,
    ) -> RiskSignal | None:
        """Flags borrowers whose cash flow has dropped significantly."""
        if avg_monthly_inflow <= 0:
            return None
        drop_ratio = (avg_monthly_inflow - current_monthly_inflow) / avg_monthly_inflow
        if drop_ratio < self.cash_flow_drop_threshold:
            return None
        severity = "medium" if drop_ratio <= 0.50 else "high"
        return RiskSignal(
            signal_type="cash_flow_drop",
            severity=severity,
            description=f"cash flow dropped by {drop_ratio:.1%}",
            metric_value=drop_ratio,
            threshold=self.cash_flow_drop_threshold,
        )

    def evaluate_bounce_events(self, bounce_count: int) -> RiskSignal | None:
        """Flags borrowers with excessive bounced transactions."""
        if bounce_count < self.bounce_event_threshold:
            return None
        return RiskSignal(
            signal_type="bounce_events",
            severity="high",
            description=f"{bounce_count} bounced transactions in evaluation window",
            metric_value=float(bounce_count),
            threshold=float(self.bounce_event_threshold),
        )

    def evaluate_utilization_spike(
        self,
        current_utilization: float,
        historical_avg_utilization: float,
    ) -> RiskSignal | None:
        """Flags borrowers whose credit utilization has spiked."""
        if historical_avg_utilization <= 0:
            spike = current_utilization
        else:
            spike = (current_utilization - historical_avg_utilization) / historical_avg_utilization
        if spike < self.utilization_spike_threshold:
            return None
        severity = "medium" if spike <= 0.40 else "high"
        return RiskSignal(
            signal_type="utilization_spike",
            severity=severity,
            description=f"credit utilization spiked by {spike:.1%}",
            metric_value=spike,
            threshold=self.utilization_spike_threshold,
        )

    def evaluate_borrower(
        self,
        days_overdue: float = 0.0,
        current_monthly_inflow: float = 0.0,
        avg_monthly_inflow: float = 0.0,
        bounce_count: int = 0,
        current_utilization: float = 0.0,
        historical_avg_utilization: float = 0.0,
    ) -> dict[str, Any]:
        """Runs full evaluation and returns signals plus composite risk score."""
        signals: list[RiskSignal] = []

        for fn, kwargs in [
            (self.evaluate_payment_delay, {"days_overdue": days_overdue}),
            (
                self.evaluate_cash_flow_drop,
                {
                    "current_monthly_inflow": current_monthly_inflow,
                    "avg_monthly_inflow": avg_monthly_inflow,
                },
            ),
            (self.evaluate_bounce_events, {"bounce_count": bounce_count}),
            (
                self.evaluate_utilization_spike,
                {
                    "current_utilization": current_utilization,
                    "historical_avg_utilization": historical_avg_utilization,
                },
            ),
        ]:
            signal = fn(**kwargs)
            if signal is not None:
                signals.append(signal)

        score = self._compute_score(signals)
        logger.info(
            "early_warning_evaluated",
            signals=len(signals),
            score=score,
        )
        return {
            "signals": [
                {
                    "signal_type": s.signal_type,
                    "severity": s.severity,
                    "description": s.description,
                    "metric_value": s.metric_value,
                    "threshold": s.threshold,
                }
                for s in signals
            ],
            "score": score,
            "risk_level": self._score_to_level(score),
        }

    @staticmethod
    def _compute_score(signals: list[RiskSignal]) -> float:
        weights = {"low": 1.0, "medium": 3.0, "high": 6.0, "critical": 10.0}
        if not signals:
            return 0.0
        total = sum(weights.get(s.severity, 1.0) for s in signals)
        return min(total, 100.0)

    @staticmethod
    def _score_to_level(score: float) -> str:
        if score <= 5.0:
            return "low"
        if score <= 15.0:
            return "medium"
        if score <= 30.0:
            return "high"
        return "critical"
