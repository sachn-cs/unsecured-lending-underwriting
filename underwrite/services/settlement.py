# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Settlement — final accounting and reconciliation.

Listens for ``default.occurred`` and emits a ``settlement.completed``
event with the net P&L impact.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Sqlite, Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator


class Handler(StatefulService):
    """Handles final settlement and loss recognition."""

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: Store | Sqlite | Store | Sqlite | Store | Sqlite | Store | Sqlite,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
    ) -> None:
        deps = Dependencies(
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
        super().__init__(
            name=name,
            bus=deps.bus,
            store=deps.store,
            metrics=deps.metrics,
            health=deps.health,
            authz=deps.authz,
            tracer=deps.tracer,
            saga=deps.saga,
            supervisor=deps.supervisor,
            secrets_manager=deps.secrets_manager,
            max_concurrent=deps.max_concurrent,
        )
        self.settlements_list: list[dict[str, Any]] = []
        self.repo: TypedStoreRepository[list[dict[str, Any]]] = self.store_repo("settlements", list)

    def start(self) -> None:
        """Load persisted settlement records when the service starts."""
        super().start()
        loaded = self.repo.load(default=[])
        if loaded:
            self.settlements_list = loaded

    @property
    def settlements(self) -> list[dict[str, Any]]:
        """Return all completed settlement records.

        Returns:
            List of settlement record dicts.
        """
        with self.state_lock:
            return list(self.settlements_list)

    def handle(self, event: Message) -> None:
        """Process a default event and emit a settlement.

        Args:
            event: The incoming domain event.
        """
        if event.event_type != Type.DEFAULT_OCCURRED:
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
            self.settlements_list.append(record)
            self.sync_store()

        self.emit(
            Type.SETTLEMENT_COMPLETED,
            {
                "borrower": borrower,
                "principal": principal,
                "loss": principal,
            },
            correlation_id=event.correlation_id,
        )

    def sync_store(self) -> None:
        """Persist the in-memory settlements to the shared store."""
        self.repo.save(self.settlements_list)
