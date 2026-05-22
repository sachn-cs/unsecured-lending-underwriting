"""Fee assessment service.

Calculates and tracks fees: late payment fees, origination fees,
prepayment penalties, and service charges.  Emits ``fee.assessed``
when a fee is applied to a loan.
"""

from __future__ import annotations

from datetime import datetime, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService
from underwrite.validate import get_finite

FEE_SCHEDULES: dict[str, float] = {
    "late_payment": 25.0,
    "origination": 0.01,
    "prepayment": 0.005,
    "service": 5.0,
}


class FeeService(NanoService):
    """Manages fee assessment, tracking, and lifecycle."""

    def handle(self, event: Event) -> None:
        """Assess and pay fees based on incoming events.

        Supports fee assessment (``fee.assess``), fee payment (``fee.pay``),
        and automatic late-payment fees on overdue loans.

        Args:
            event: The incoming event.
        """
        if event.event_type == "fee.assess":
            loan_id: str = event.payload.get("loan_id", "")
            fee_type: str = event.payload.get("fee_type", "")
            if not loan_id or fee_type not in FEE_SCHEDULES:
                return
            amount: float = FEE_SCHEDULES[fee_type]
            if fee_type == "origination":
                principal: float = get_finite(event.payload, "principal", 0.0)
                amount = principal * FEE_SCHEDULES["origination"]

            fee_id: str = f"fee_{loan_id}_{fee_type}_{int(datetime.now(timezone.utc).timestamp())}"
            self.store.set(
                f"fee:{fee_id}", {
                    "loan_id": loan_id,
                    "fee_type": fee_type,
                    "amount": amount,
                    "assessed_at": datetime.now(timezone.utc).isoformat(),
                    "paid": False,
                })
            self.emit(EventType.FEE_ASSESSED, {
                "fee_id": fee_id,
                "loan_id": loan_id,
                "fee_type": fee_type,
                "amount": amount,
            },
                      correlation_id=event.correlation_id)

        elif event.event_type == "fee.pay":
            fee_id = event.payload.get("fee_id", "")
            record = self.store.get(f"fee:{fee_id}")
            if record and not record["paid"]:
                record["paid"] = True
                record["paid_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"fee:{fee_id}", record)

        elif event.event_type == EventType.PAYMENT_OVERDUE:
            loan_id = event.payload.get("loan_id", "")
            if loan_id:
                self.handle(
                    Event(event_type="fee.assess",
                          source=self.service_id,
                          payload={
                              "loan_id": loan_id,
                              "fee_type": "late_payment"
                          },
                          correlation_id=event.correlation_id))
