"""Loan servicing service.

Manages the post-origination lifecycle of loans: tracks active loans,
status transitions, and coordinates with payment, collection, and
settlement services.
"""

from __future__ import annotations

from datetime import datetime, timezone

from underwrite.__events__ import Event
from underwrite.services.base import NanoService


class ServicingService(NanoService):
    """Tracks active loan state, status transitions, and outstanding balances."""

    def handle(self, event: Event) -> None:
        if event.event_type == "loan.originated":
            loan_id: str = event.payload.get("loan_id", "")
            borrower: str = event.payload.get("borrower", "")
            principal: float = float(event.payload.get("principal", 0))
            if not loan_id:
                return
            self.store.set(
                f"loan:{loan_id}", {
                    "borrower": borrower,
                    "principal": principal,
                    "outstanding": principal,
                    "status": "active",
                    "originated_at": datetime.now(timezone.utc).isoformat(),
                })

        elif event.event_type == "repaid":
            loan_id = event.payload.get("loan_id", "")
            amount: float = float(event.payload.get("amount", 0))
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["outstanding"] = max(0.0, record["outstanding"] - amount)
                if record["outstanding"] <= 0:
                    record["status"] = "paid"
                    record["paid_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"loan:{loan_id}", record)

        elif event.event_type == "default.occurred":
            loan_id = event.payload.get("loan_id", "")
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["status"] = "defaulted"
                record["defaulted_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"loan:{loan_id}", record)
