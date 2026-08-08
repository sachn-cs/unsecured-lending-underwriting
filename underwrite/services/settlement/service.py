"""Settlement — final accounting and reconciliation.

Listens for ``default.occurred`` and emits a ``settlement.completed``
event with the net P&L impact.
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.validate import get_finite, get_non_empty


class SettlementHandler(StatefulService):
    """Handles final settlement and loss recognition."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__settlements: list[dict[str, Any]] = []
        self.repo: TypedStoreRepository[list[dict[str, Any]]] = self.store_repo("settlements", list)
        loaded = self.repo.load(default=[])
        if loaded:
            self.__settlements = loaded

    @property
    def settlements(self) -> list[dict[str, Any]]:
        """Return all completed settlement records.

        Returns:
            List of settlement record dicts.
        """
        with self.state_lock:
            return list(self.__settlements)

    def handle(self, event: Event) -> None:
        """Process a default event and emit a settlement.

        Args:
            event: The incoming domain event.
        """
        if event.event_type != EventType.DEFAULT_OCCURRED:
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")

        with self.state_lock:
            record = {
                "borrower": borrower,
                "principal": principal,
                "loss": principal,
                "status": "settled",
            }
            self.__settlements.append(record)
            self.__sync()

        self.emit(
            EventType.SETTLEMENT_COMPLETED,
            {
                "borrower": borrower,
                "principal": principal,
                "loss": principal,
            },
            correlation_id=event.correlation_id,
        )

    def __sync(self) -> None:
        """Persist the in-memory settlements to the shared store."""
        self.repo.save(self.__settlements)
