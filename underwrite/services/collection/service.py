"""Collection — tracks repayment schedule and overdue accounts.

Listens for ``loan.originated`` and ``repaid`` events to maintain
an amortisation schedule and flag overdue accounts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty


class CollectionService(NanoService):
    """Tracks repayment schedules and flags overdue accounts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__loans: dict[str, dict[str, Any]] = {}

    def handle(self, event: Event) -> None:
        if event.event_type == EventType.LOAN_ORIGINATED:
            p = event.payload
            borrower: str = get_non_empty(p, "borrower")
            principal: float = get_finite(p, "principal")
            term: float = get_finite(p, "term", 1.0)
            monthly: float = principal / term if term > 0 else 0.0
            self.__loans[borrower] = {
                "principal": principal,
                "term": term,
                "monthly": monthly,
                "paid": 0.0,
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.emit(EventType.COLLECTION_UPDATED, {
                "borrower": borrower,
                "monthly": round(monthly, 2),
                "total": principal,
                "status": "active",
            },
                      correlation_id=event.correlation_id)
        elif event.event_type == EventType.REPAID:
            p = event.payload
            user: str = get_non_empty(p, "user")
            delta: float = get_finite(p, "delta_earned")
            loan = self.__loans.get(user)
            if loan:
                loan["paid"] += delta
                if loan["paid"] >= loan["principal"]:
                    loan["status"] = "closed"
                self.emit(EventType.COLLECTION_UPDATED, {
                    "borrower": user,
                    "paid": round(loan["paid"], 2),
                    "remaining": round(loan["principal"] - loan["paid"], 2),
                    "status": loan["status"],
                },
                          correlation_id=event.correlation_id)

    def get(self, borrower: str) -> dict[str, Any] | None:
        """Retrieve the collection record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Collection record dict or None if not found.
        """
        return self.__loans.get(borrower)
