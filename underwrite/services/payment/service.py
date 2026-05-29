"""Payment processing service.

Handles payment scheduling, receipt, and overdue detection.  Emits
``payment.received`` when a payment comes in, ``payment.due`` when a
payment is expected, and ``payment.overdue`` when a payment is late.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService
from underwrite.validate import get_finite


class PaymentService(NanoService):
    """Manages payment scheduling, receipt tracking, and delinquency detection."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__payments: dict[str, dict[str, Any]] = {}
        self.__load_store()

    def handle(self, event: Event) -> None:
        with self.__lock:
            if event.event_type == EventType.PAYMENT_RECEIVE:
                loan_id: str = event.payload.get("loan_id", "")
                amount: float = get_finite(event.payload, "amount", 0.0)
                if not loan_id or amount <= 0:
                    return
                payment_id: str = f"pay_{loan_id}_{int(datetime.now(timezone.utc).timestamp())}"
                receipt = {
                    "loan_id": loan_id,
                    "amount": amount,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }
                self.store.set(f"payment:{payment_id}", receipt)
                self.__payments[f"payment:{payment_id}"] = receipt
                self.__sync_store()
                self.emit(EventType.PAYMENT_RECEIVED, {
                    "payment_id": payment_id,
                    "loan_id": loan_id,
                    "amount": amount,
                },
                          correlation_id=event.correlation_id)

            elif event.event_type == EventType.PAYMENT_SCHEDULE:
                loan_id = event.payload.get("loan_id", "")
                due_date: str = event.payload.get("due_date", "")
                amount = get_finite(event.payload, "amount", 0.0)
                if not loan_id or not due_date:
                    return
                schedule_key: str = f"schedule:{loan_id}:{due_date}"
                schedule = {
                    "loan_id": loan_id,
                    "due_date": due_date,
                    "amount": amount,
                    "status": "pending",
                }
                self.store.set(schedule_key, schedule)
                self.__payments[schedule_key] = schedule
                self.__sync_store()
                self.emit(EventType.PAYMENT_DUE, {
                    "loan_id": loan_id,
                    "due_date": due_date,
                    "amount": amount,
                },
                          correlation_id=event.correlation_id)

            elif event.event_type == EventType.PAYMENT_CHECK_OVERDUE:
                loan_id = event.payload.get("loan_id", "")
                if not loan_id:
                    return
                cutoff: datetime = datetime.now(
                    timezone.utc) - timedelta(days=30)
                for key in self.store.keys(f"schedule:{loan_id}:"):
                    raw = self.store.get(key)
                    if raw is None:
                        continue
                    sched: dict[str, object] = raw
                    if sched.get("status") == "pending":
                        due_str = sched.get("due_date", "")
                        due = datetime.fromisoformat(str(due_str))
                        if due < cutoff:
                            sched["status"] = "overdue"
                            self.store.set(key, sched)
                            self.__payments[key] = dict(sched)
                            self.__sync_store()
                            self.emit(EventType.PAYMENT_OVERDUE, {
                                "loan_id": loan_id,
                                "due_date": sched["due_date"],
                                "amount": sched["amount"],
                            },
                                      correlation_id=event.correlation_id)

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        """Restore payment records from the store, if present."""
        with self.__lock:
            raw = self.store.get(f"{self.service_id}:payments")
            if raw is not None and isinstance(raw, dict):
                self.__payments = dict(raw)

    def __sync_store(self) -> None:
        """Persist the current payment records to the store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:payments", dict(self.__payments))
