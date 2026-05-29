"""Statement generation service.

Produces periodic account statements showing transactions, outstanding
balance, fees, and payment history.  Emits ``statement.generated``
when a statement is produced.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService
from underwrite.validate import require_finite


class StatementService(NanoService):
    """Generates account statements showing loan activity and current status."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__statements: dict[str, dict[str, Any]] = {}
        self.__load_store()

    def handle(self, event: Event) -> None:
        if event.event_type == EventType.STATEMENT_GENERATE:
            loan_id: str = event.payload.get("loan_id", "")
            period_start: str = event.payload.get("period_start", "")
            period_end: str = event.payload.get("period_end", "")
            if not loan_id or not period_start:
                return

            statement_id: str = f"stmt_{loan_id}_{period_start}"
            if self.store.exists(f"statement:{statement_id}"):
                return

            transactions: list[dict[str, Any]] = []
            for key in self.store.keys(f"payment:{loan_id}"):
                payment = self.store.get(key)
                if payment:
                    transactions.append(payment)
            total_paid: float = sum(
                require_finite(t.get("amount", 0), "amount")
                for t in transactions)

            loan = self.store.get(f"loan:{loan_id}")
            outstanding: float = require_finite(loan.get("outstanding", 0),
                                                "outstanding") if loan else 0.0

            statement: dict[str, Any] = {
                "statement_id":
                    statement_id,
                "loan_id":
                    loan_id,
                "period_start":
                    period_start,
                "period_end":
                    period_end or datetime.now(timezone.utc).isoformat(),
                "outstanding":
                    outstanding,
                "total_paid":
                    total_paid,
                "transaction_count":
                    len(transactions),
                "generated_at":
                    datetime.now(timezone.utc).isoformat(),
            }
            self.store.set(f"statement:{statement_id}", statement)
            self.__statements[f"statement:{statement_id}"] = dict(statement)
            self.__sync_store()
            self.emit(EventType.STATEMENT_GENERATED, {
                "statement_id": statement_id,
                "loan_id": loan_id,
                "outstanding": outstanding,
                "total_paid": total_paid,
            },
                      correlation_id=event.correlation_id)

        elif event.event_type == EventType.COLLECTION_UPDATED:
            loan_id = event.payload.get("loan_id", "")
            if loan_id:
                self.store.set(
                    f"stmt_trigger:{loan_id}:{datetime.now(timezone.utc).isoformat()}",
                    {
                        "loan_id": loan_id,
                        "trigger": "collection_update",
                    })

        elif event.event_type == EventType.PAYMENT_RECEIVED:
            loan_id = event.payload.get("loan_id", "")
            if loan_id:
                self.store.set(
                    f"stmt_trigger:{loan_id}:{datetime.now(timezone.utc).isoformat()}",
                    {
                        "loan_id": loan_id,
                        "trigger": "payment",
                    })

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        """Restore statement records from the store, if present."""
        with self.__lock:
            raw = self.store.get(f"{self.service_id}:statements")
            if raw is not None and isinstance(raw, dict):
                self.__statements = dict(raw)

    def __sync_store(self) -> None:
        """Persist the current statement records to the store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:statements",
                           dict(self.__statements))
