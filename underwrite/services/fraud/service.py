"""Fraud detection — velocity checks, wash lending, and rule-based alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty


class FraudService(NanoService):
    """Detects wash lending, burst origination patterns, and configurable fraud rules."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the fraud service with an empty activity record store.

        Args:
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(**kwargs)
        self.__records: dict[str, list[dict[str, Any]]] = {}

    def handle(self, event: Event) -> None:
        """Check loan origination and repayment events against fraud rules.

        Triggers alerts for wash lending cycles, velocity bursts, and
        large-value originations.

        Args:
            event: The incoming event. LOAN_ORIGINATED and REPAID are processed.
        """
        if event.event_type == EventType.LOAN_ORIGINATED:
            borrower: str = get_non_empty(event.payload, "borrower")
            principal: float = get_finite(event.payload, "principal")
            self.__record(borrower, "origination", principal)
            self.__check_wash(borrower, event.correlation_id)
            self.__check_burst(borrower, event.correlation_id)
            if principal > 1_000_000:
                self.emit(EventType.FRAUD_ALERT, {
                    "rule": "large_origination",
                    "borrower": borrower,
                    "principal": principal,
                },
                          correlation_id=event.correlation_id)
        elif event.event_type == EventType.REPAID:
            user: str = get_non_empty(event.payload, "user")
            delta: float = get_finite(event.payload, "delta_earned")
            self.__record(user, "repayment", delta)
            self.__check_wash(user, event.correlation_id)

    def __record(self, borrower: str, event_type: str, amount: float) -> None:
        self.__records.setdefault(borrower, []).append({
            "event_type": event_type,
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def __check_wash(self, borrower: str, correlation_id: str) -> None:
        records = self.__records.get(borrower, [])
        cycles: int = 0
        i: int = 0
        while i < len(records) - 1:
            if records[i]["event_type"] == "origination" and records[
                    i + 1]["event_type"] == "repayment":
                cycles += 1
                i += 2
            else:
                i += 1
        if cycles >= 3:
            self.emit(EventType.WASH_FLAG, {
                "borrower": borrower,
                "cycles": cycles,
                "score": min(100.0, cycles * 16.67),
            },
                      correlation_id=correlation_id)

    def __check_burst(self, borrower: str, correlation_id: str) -> None:
        records = self.__records.get(borrower, [])
        recent = [r for r in records if r["event_type"] == "origination"]
        if len(recent) > 3:
            self.emit(EventType.VELOCITY_FLAG, {
                "borrower": borrower,
                "count": len(recent),
            },
                      correlation_id=correlation_id)
