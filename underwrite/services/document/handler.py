"""Document - generates and manages loan document references.

Listens for underwriter.approved events, creates document records,
and emits document.generated.
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__metrics__ import SystemClock
from underwrite.__value_objects__ import IdGenerator
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.validate import get_finite, get_non_empty

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer


class DocumentHandler(StatefulService):
    """Generates loan document references after approval."""

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
        self.__documents: dict[str, list[dict[str, Any]]] = {}
        self.__id_generator: IdGenerator = IdGenerator()
        self.repo: TypedStoreRepository[dict[str, list[dict[str, Any]]]] = self.store_repo("documents", dict)

    def start(self) -> None:
        """Load persisted document records when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.__documents = loaded

    def handle(self, event: Event) -> None:
        """Generate a document record on underwriter approval.

        Args:
            event: The incoming domain event.
        """
        if event.event_type != EventType.UNDERWRITER_APPROVED:
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")
        doc_id: str = self.__id_generator.next()

        record = {
            "doc_id": doc_id,
            "borrower": borrower,
            "principal": principal,
            "status": "generated",
        }
        with self.state_lock:
            self.__documents.setdefault(borrower, []).append(record)
            self.repo.save(self.__documents)

        self.emit(
            EventType.DOCUMENT_GENERATED,
            {
                "borrower": borrower,
                "principal": principal,
                "doc_id": doc_id,
            },
            correlation_id=event.correlation_id,
        )

    def documents_for(self, borrower: str) -> list[dict[str, Any]]:
        """Retrieve all documents generated for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            List of document records for the borrower.
        """
        with self.state_lock:
            return list(self.__documents.get(borrower, []))
