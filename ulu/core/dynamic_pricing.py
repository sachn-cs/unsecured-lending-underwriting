"""Dynamic rate pricing based on borrower risk and system utilization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicRate:
    """Rate components computed for a borrower."""

    protocol_rate: float
    delegation_rate: float
    risk_adjustment: float
    utilization_adjustment: float


class DynamicPricingService:
    """Adjusts protocol and delegation rates using risk score and utilization."""

    def __init__(
        self,
        base_protocol_rate: float = 0.15,
        base_delegation_rate: float = 0.10,
        risk_sensitivity: float = 0.5,
        utilization_sensitivity: float = 0.3,
        max_rate_cap: float = 1.0,
    ) -> None:
        self.base_protocol_rate = base_protocol_rate
        self.base_delegation_rate = base_delegation_rate
        self.risk_sensitivity = risk_sensitivity
        self.utilization_sensitivity = utilization_sensitivity
        self.max_rate_cap = max_rate_cap

    def compute_rates(
        self,
        risk_score: float,
        utilization: float,
    ) -> DynamicRate:
        """Returns dynamic rates given borrower risk and system utilization.

        Args:
            risk_score: Probability of default (0.0 - 1.0).
            utilization: Fraction of delegated capacity in use (0.0 - 1.0).
        """
        clamped_risk = max(0.0, min(1.0, risk_score))
        clamped_util = max(0.0, min(1.0, utilization))

        risk_adjustment = self.risk_sensitivity * clamped_risk
        util_adjustment = self.utilization_sensitivity * clamped_util

        protocol_rate = self.base_protocol_rate + risk_adjustment + util_adjustment
        delegation_rate = self.base_delegation_rate * (1.0 - clamped_util)

        protocol_rate = min(protocol_rate, self.max_rate_cap)
        delegation_rate = min(delegation_rate, self.max_rate_cap)

        return DynamicRate(
            protocol_rate=protocol_rate,
            delegation_rate=delegation_rate,
            risk_adjustment=risk_adjustment,
            utilization_adjustment=util_adjustment,
        )
