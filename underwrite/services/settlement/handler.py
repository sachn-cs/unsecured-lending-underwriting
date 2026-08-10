"""Settlement — final accounting and reconciliation.

Listens for ``default.occurred`` and emits a ``settlement.completed``
event with the net P&L impact.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.events import Event, EventType
from underwrite.health import Checks
from underwrite.identity import Identity
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator


class SettlementHandler(StatefulService):
    """Handles final settlement and loss recognition."""

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
    ) -> None:
        super().__init__(
            service_id=service_id,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__settlements: list[dict[str, Any]] = []
        self.repo: TypedStoreRepository[list[dict[str, Any]]] = self.store_repo("settlements", list)

    def start(self) -> None:
        """Load persisted settlement records when the service starts."""
        super().start()
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
        borrower: str = PayloadValidator().non_empty(p, "borrower")
        principal: float = PayloadValidator().finite(p, "principal")

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
