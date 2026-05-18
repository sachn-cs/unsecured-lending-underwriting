"""Real-time collateralization ratio engine."""

from __future__ import annotations

from ulu.domain.events import CollateralBreachEvent


class CollateralizationRatioEngine:
    """Computes aggregate collateralization ratios and detects breaches."""

    def __init__(self, min_ratio: float = 0.05) -> None:
        if not (0.0 <= min_ratio <= 1.0):
            raise ValueError("min_ratio must be in [0, 1]")
        self.min_ratio = min_ratio

    def compute_ratio(self, total_collateral_value: float, total_outstanding_principal: float) -> float:
        if total_outstanding_principal < 0:
            raise ValueError("total_outstanding_principal must be non-negative")
        if total_outstanding_principal == 0:
            return 1.0
        if total_collateral_value < 0:
            raise ValueError("total_collateral_value must be non-negative")
        return total_collateral_value / total_outstanding_principal

    def check_breach(
        self, owner_id: str, collateral_value: float, outstanding_principal: float
    ) -> CollateralBreachEvent | None:
        ratio = self.compute_ratio(collateral_value, outstanding_principal)
        if ratio < self.min_ratio:
            return CollateralBreachEvent(
                event_type="collateral_breach",
                payload={
                    "owner_id": owner_id,
                    "current_ratio": ratio,
                    "required_ratio": self.min_ratio,
                },
                owner_id=owner_id,
                current_ratio=ratio,
                required_ratio=self.min_ratio,
            )
        return None
