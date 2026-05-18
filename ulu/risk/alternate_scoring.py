"""Alternate data scoring using UPI, telecom, and utility signals.

Item 39 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class UpiTransactionPattern:
    """UPI transaction-derived creditworthiness signals."""

    monthly_volume: float
    avg_transaction_size: float
    merchant_diversity_score: int
    failure_rate: float
    late_night_ratio: float


@dataclass
class TelecomData:
    """Telecom payment and usage signals."""

    tenure_months: int
    on_time_payment_ratio: float
    average_monthly_bill: float
    plan_category: str


@dataclass
class UtilityPaymentPattern:
    """Utility bill payment signals."""

    electricity_on_time_ratio: float
    water_on_time_ratio: float
    gas_on_time_ratio: float
    avg_monthly_spend: float


class AlternateDataScoringService:
    """Computes credit score components from non-traditional data sources."""

    def __init__(self) -> None:
        pass

    def score_upi_pattern(self, pattern: UpiTransactionPattern) -> float:
        """Returns a UPI-based score between 0.0 and 1.0."""
        if pattern.monthly_volume <= 0:
            return 0.0
        volume_score = min(pattern.monthly_volume / 50000.0, 1.0)
        diversity_score = min(pattern.merchant_diversity_score / 20.0, 1.0)
        reliability_score = max(0.0, 1.0 - pattern.failure_rate)
        return (volume_score * 0.4 + diversity_score * 0.3 + reliability_score * 0.3)

    def score_telecom(self, data: TelecomData) -> float:
        """Returns a telecom-based score between 0.0 and 1.0."""
        tenure_score = min(data.tenure_months / 24.0, 1.0)
        payment_score = data.on_time_payment_ratio
        return (tenure_score * 0.3 + payment_score * 0.7)

    def score_utility(self, pattern: UtilityPaymentPattern) -> float:
        """Returns a utility-based score between 0.0 and 1.0."""
        avg_on_time = (
            pattern.electricity_on_time_ratio
            + pattern.water_on_time_ratio
            + pattern.gas_on_time_ratio
        ) / 3.0
        return max(0.0, min(avg_on_time, 1.0))

    def composite_alternate_score(
        self,
        upi: UpiTransactionPattern | None = None,
        telecom: TelecomData | None = None,
        utility: UtilityPaymentPattern | None = None,
    ) -> dict[str, Any]:
        """Combines available alternate data signals into a composite score."""
        scores: dict[str, float] = {}
        if upi is not None:
            scores["upi"] = self.score_upi_pattern(upi)
        if telecom is not None:
            scores["telecom"] = self.score_telecom(telecom)
        if utility is not None:
            scores["utility"] = self.score_utility(utility)

        if not scores:
            return {"score": 0.0, "components": {}, "data_availability": "none"}

        composite = sum(scores.values()) / len(scores)
        availability = "partial" if len(scores) < 3 else "full"
        return {
            "score": composite,
            "components": scores,
            "data_availability": availability,
        }
