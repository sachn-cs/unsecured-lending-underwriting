"""Loan servicing service.

Manages the post-origination lifecycle of loans: tracks active loans,
status transitions, and coordinates with payment, collection, and
settlement services.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService
from underwrite.validate import get_finite

logger = logging.getLogger(__name__)


class ServicingService(NanoService):
    """Tracks active loan state, status transitions, and outstanding balances."""

    def handle(self, event: Event) -> None:
        if event.event_type == EventType.LOAN_ORIGINATED:
            loan_id: str = event.payload.get("loan_id", "")
            borrower: str = event.payload.get("borrower", "")
            principal: float = get_finite(event.payload, "principal", 0.0)
            if not loan_id:
                logger.warning("dropping LOAN_ORIGINATED with missing loan_id")
                return
            self.store.set(
                f"loan:{loan_id}", {
                    "borrower": borrower,
                    "principal": principal,
                    "outstanding": principal,
                    "status": "active",
                    "originated_at": datetime.now(timezone.utc).isoformat(),
                })

        elif event.event_type == EventType.REPAID:
            loan_id = event.payload.get("loan_id", "")
            if not loan_id:
                logger.warning("dropping REPAID with missing loan_id")
                return
            amount: float = get_finite(event.payload, "amount", 0.0)
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["outstanding"] = max(0.0, record["outstanding"] - amount)
                if record["outstanding"] <= 0:
                    record["status"] = "paid"
                    record["paid_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"loan:{loan_id}", record)

        elif event.event_type == EventType.DEFAULT_OCCURRED:
            loan_id = event.payload.get("loan_id", "")
            if not loan_id:
                logger.warning("dropping DEFAULT_OCCURRED with missing loan_id")
                return
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["status"] = "defaulted"
                record["defaulted_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"loan:{loan_id}", record)
