"""Fee assessment service.

Calculates and tracks fees: late payment fees, origination fees,
prepayment penalties, and service charges.  Emits ``fee.assessed``
when a fee is applied to a loan.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService
from underwrite.validate import get_finite

logger = logging.getLogger(__name__)

DEFAULT_FEE_SCHEDULES: dict[str, float] = {
    "late_payment": 25.0,
    "origination": 0.01,
    "prepayment": 0.005,
    "service": 5.0,
}


class FeeService(NanoService):
    """Manages fee assessment, tracking, and lifecycle."""

    def __init__(self, **kwargs: Any) -> None:
        self.__schedules: dict[str, float] = kwargs.pop("fee_schedules", dict(DEFAULT_FEE_SCHEDULES))
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__fees: dict[str, dict[str, Any]] = {}
        self.__load_store()

    def __assess(self, loan_id: str, fee_type: str, principal: float = 0.0, correlation_id: str = "") -> None:
        """Assess a fee and persist it.  Called directly (not via bus)."""
        with self.__lock:
            schedules = self.__schedules
            if not loan_id or fee_type not in schedules:
                if not loan_id:
                    logger.warning("fee.assess missing loan_id, ignored")
                else:
                    logger.warning("fee.assess with unknown fee_type %r, ignored", fee_type)
                return
            if fee_type == "origination":
                amount = principal * schedules["origination"]
            else:
                amount = schedules[fee_type]

            import math as _math
            if not _math.isfinite(amount):
                logger.error("non-finite fee amount %s for loan %s, skipping", amount, loan_id)
                return
            fee_id: str = f"fee_{loan_id}_{fee_type}_{int(datetime.now(timezone.utc).timestamp())}"
            fee_record = {
                "loan_id": loan_id,
                "fee_type": fee_type,
                "amount": amount,
                "assessed_at": datetime.now(timezone.utc).isoformat(),
                "paid": False,
            }
            self.store.set(f"fee:{fee_id}", fee_record)
            self.__fees[f"fee:{fee_id}"] = fee_record
            self.__sync_store()
            self.emit(EventType.FEE_ASSESSED, {
                "fee_id": fee_id,
                "loan_id": loan_id,
                "fee_type": fee_type,
                "amount": amount,
            },
                      correlation_id=correlation_id)

    def handle(self, event: Event) -> None:
        """Assess and pay fees based on incoming events.

        Supports fee assessment (``fee.assess``), fee payment (``fee.pay``),
        and automatic late-payment fees on overdue loans.

        Args:
            event: The incoming event.
        """
        with self.__lock:
            if event.event_type == EventType.FEE_ASSESS:
                self.__assess(
                    loan_id=event.payload.get("loan_id", ""),
                    fee_type=event.payload.get("fee_type", ""),
                    principal=get_finite(event.payload, "principal", 0.0),
                    correlation_id=event.correlation_id,
                )

            elif event.event_type == EventType.FEE_PAY:
                fee_id = event.payload.get("fee_id", "")
                record = self.store.get(f"fee:{fee_id}")
                if record and not record["paid"]:
                    record["paid"] = True
                    record["paid_at"] = datetime.now(timezone.utc).isoformat()
                    self.store.set(f"fee:{fee_id}", record)
                    self.__fees[f"fee:{fee_id}"] = dict(record)
                    self.__sync_store()

            elif event.event_type == EventType.PAYMENT_OVERDUE:
                loan_id = event.payload.get("loan_id", "")
                if not loan_id:
                    logger.warning("PAYMENT_OVERDUE missing loan_id, skipped")
                    return
                self.__assess(
                    loan_id=loan_id,
                    fee_type="late_payment",
                    correlation_id=event.correlation_id,
                )

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        """Restore fee records from the store, if present."""
        with self.__lock:
            raw = self.store.get(f"{self.service_id}:fees")
            if raw is not None and isinstance(raw, dict):
                self.__fees = dict(raw)

    def __sync_store(self) -> None:
        """Persist the current fee records to the store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:fees", dict(self.__fees))

    def health_check(self) -> dict[str, Any]:
        """Fee-specific health: reports total fee count and pending fees."""
        with self.__lock:
            pending = sum(1 for r in self.__fees.values() if not r.get("paid", False))
            return {
                **super().health_check(),
                "fee_count": len(self.__fees),
                "pending_fees": pending,
            }
