"""Disbursement - processes loan payout after document generation.

Listens for document.generated events and emits
disbursement.processed.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator


class Handler(StatefulService):
    """Processes loan disbursement to borrower accounts."""

    def __init__(
        self,
        name: str,
        bus: EventBus,
        store: Store,
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
        super().__init__(
            name=name,
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
        self.__clock: SystemClock = SystemClock()
        self.__disbursements: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("disbursements", dict)
        loaded = self.repo.load(default={})
        if loaded:
            self.__disbursements = loaded

    def handle(self, event: Message) -> None:
        """Process document.generated events to trigger disbursement.

        Args:
            event: The incoming domain event.
        """
        if event.event_type != Type.DOCUMENT_GENERATED:
            return
        p = event.payload
        borrower: str = PayloadValidator().non_empty(p, "borrower")
        principal: float = PayloadValidator().finite(p, "principal")
        doc_id: str = p.get("doc_id", "")

        with self.state_lock:
            if borrower in self.__disbursements:
                logger.warning("duplicate disbursement attempted for {}, skipping", borrower)
                return
            record = {
                "borrower": borrower,
                "principal": principal,
                "doc_id": doc_id,
                "disbursed_at": self.__clock.iso(),
                "status": "disbursed",
            }
            self.__disbursements[borrower] = record
            self.repo.save(self.__disbursements)

        self.emit(
            Type.DISBURSEMENT_PROCESSED,
            {
                "borrower": borrower,
                "principal": principal,
                "doc_id": doc_id,
            },
            correlation_id=event.correlation_id,
        )

    def get(self, borrower: str) -> dict[str, Any] | None:
        """Retrieve the disbursement record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Disbursement record dict or None if not yet disbursed.
        """
        with self.state_lock:
            return self.__disbursements.get(borrower)
