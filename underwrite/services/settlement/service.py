"""Settlement — final accounting and reconciliation.

Listens for ``default.occurred`` and emits a ``settlement.completed``
event with the net P&L impact.
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty


class SettlementService(NanoService):
    """Handles final settlement and loss recognition."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__settlements: list[dict[str, Any]] = []

    @property
    def settlements(self) -> list[dict[str, Any]]:
        """Return all completed settlement records.

        Returns:
            List of settlement record dicts.
        """
        return list(self.__settlements)

    def handle(self, event: Event) -> None:
        if event.event_type != EventType.DEFAULT_OCCURRED:
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")

        record = {
            "borrower": borrower,
            "principal": principal,
            "loss": principal,
            "status": "settled",
        }
        self.__settlements.append(record)

        self.emit(EventType.SETTLEMENT_COMPLETED, {
            "borrower": borrower,
            "principal": principal,
            "loss": principal,
        },
                  correlation_id=event.correlation_id)
