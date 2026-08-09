"""Disbursement - processes loan payout after document generation.

Listens for document.generated events and emits
disbursement.processed.
"""

from __future__ import annotations

from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__events__ import Event, EventType
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__logger__ import logger
from underwrite.__metrics__ import MetricsCollector, SystemClock
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.validate import get_finite, get_non_empty


class DisbursementHandler(StatefulService):
    """Processes loan disbursement to borrower accounts."""

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
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
        self.__clock: SystemClock = SystemClock()
        self.__disbursements: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("disbursements", dict)
        loaded = self.repo.load(default={})
        if loaded:
            self.__disbursements = loaded

    def handle(self, event: Event) -> None:
        """Process document.generated events to trigger disbursement.

        Args:
            event: The incoming domain event.
        """
        if event.event_type != EventType.DOCUMENT_GENERATED:
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")
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
            EventType.DISBURSEMENT_PROCESSED,
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
