"""Payment processing service.

Handles payment scheduling, receipt, and overdue detection.  Emits
``payment.received`` when a payment comes in, ``payment.due`` when a
payment is expected, and ``payment.overdue`` when a payment is late.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService


class PaymentService(NanoService):
    """Manages payment scheduling, receipt tracking, and delinquency detection."""

    def handle(self, event: Event) -> None:
        if event.event_type == "payment.receive":
            loan_id: str = event.payload.get("loan_id", "")
            amount: float = float(event.payload.get("amount", 0))
            if not loan_id or amount <= 0:
                return
            payment_id: str = f"pay_{loan_id}_{int(datetime.now(timezone.utc).timestamp())}"
            self.store.set(
                f"payment:{payment_id}", {
                    "loan_id": loan_id,
                    "amount": amount,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                })
            self.emit(EventType.PAYMENT_RECEIVED, {
                "payment_id": payment_id,
                "loan_id": loan_id,
                "amount": amount,
            },
                      correlation_id=event.correlation_id)

        elif event.event_type == "payment.schedule":
            loan_id = event.payload.get("loan_id", "")
            due_date: str = event.payload.get("due_date", "")
            amount = float(event.payload.get("amount", 0))
            if not loan_id or not due_date:
                return
            schedule_key: str = f"schedule:{loan_id}:{due_date}"
            self.store.set(
                schedule_key, {
                    "loan_id": loan_id,
                    "due_date": due_date,
                    "amount": amount,
                    "status": "pending",
                })
            self.emit(EventType.PAYMENT_DUE, {
                "loan_id": loan_id,
                "due_date": due_date,
                "amount": amount,
            },
                      correlation_id=event.correlation_id)

        elif event.event_type == "payment.check_overdue":
            loan_id = event.payload.get("loan_id", "")
            if not loan_id:
                return
            cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=30)
            for key in self.store.keys(f"schedule:{loan_id}:"):
                schedule = self.store.get(key)
                if schedule and schedule.get("status") == "pending":
                    due = datetime.fromisoformat(schedule["due_date"])
                    if due < cutoff:
                        schedule["status"] = "overdue"
                        self.store.set(key, schedule)
                        self.emit(EventType.PAYMENT_OVERDUE, {
                            "loan_id": loan_id,
                            "due_date": schedule["due_date"],
                            "amount": schedule["amount"],
                        },
                                  correlation_id=event.correlation_id)
