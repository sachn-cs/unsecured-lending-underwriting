"""Pricing — computes interest rates and fees based on risk profile.

Listens for ``pricing.request`` events and emits ``pricing.computed``
with the final rate and fee breakdown.
"""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty

BASE_RATE: float = 0.08
RISK_PREMIUM_MULTIPLIER: float = 0.50


class PricingService(NanoService):
    """Computes loan pricing (rate, fees) from risk score and principal."""

    def handle(self, event: Event) -> None:
        if event.event_type != "pricing.request":
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")
        dp: float = get_finite(p, "default_probability", 0.02)

        risk_premium: float = dp * RISK_PREMIUM_MULTIPLIER
        interest_rate: float = BASE_RATE + risk_premium
        origination_fee: float = principal * 0.01

        self.emit(EventType.PRICING_COMPUTED, {
            "borrower": borrower,
            "principal": principal,
            "interest_rate": round(interest_rate, 4),
            "origination_fee": round(origination_fee, 2),
            "risk_premium": round(risk_premium, 4),
        },
                  correlation_id=event.correlation_id)
