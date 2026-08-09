"""Statement generation service.

Produces periodic account statements showing transactions, outstanding
balance, fees, and payment history.  Emits ``statement.generated``
when a statement is produced.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.__metrics__ import SystemClock
from underwrite.services.base import NanoService
from underwrite.validate import require_finite

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer


class StatementHandler(NanoService):
    """Generates account statements showing loan activity and current status."""

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
        self.handlers: dict[str, Any] = {
            EventType.STATEMENT_GENERATE: self.__on_statement_generate,
            EventType.COLLECTION_UPDATED: self.__on_collection_updated,
            EventType.PAYMENT_RECEIVED: self.__on_payment_received_trigger,
        }

    def handle(self, event: Event) -> None:
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_statement_generate(self, event: Event) -> None:
        """Generate a statement for the given loan and period.

        Args:
            event: The STATEMENT_GENERATE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        period_start: str = event.payload.get("period_start", "")
        period_end: str = event.payload.get("period_end", "")
        if not loan_id or not period_start:
            logger.warning("dropping STATEMENT_GENERATE with missing loan_id or period_start")
            return

        with self.state_lock:
            statement_id: str = f"stmt_{loan_id}_{period_start}"
            if self.store.exists(f"statement:{statement_id}"):
                return

            transactions: list[dict[str, Any]] = []
            for key in self.store.keys(f"payment:pay_{loan_id}"):
                payment = self.store.get(key)
                if payment:
                    transactions.append(payment)
            total_paid: float = sum(require_finite(t.get("amount", 0), "amount") for t in transactions)

            loan = self.store.get(f"loan:{loan_id}")
            outstanding: float = require_finite(loan.get("outstanding", 0), "outstanding") if loan else 0.0

            statement: dict[str, Any] = {
                "statement_id": statement_id,
                "loan_id": loan_id,
                "period_start": period_start,
                "period_end": period_end or self.__clock.iso(),
                "outstanding": outstanding,
                "total_paid": total_paid,
                "transaction_count": len(transactions),
                "generated_at": self.__clock.iso(),
            }
            self.store.set(f"statement:{statement_id}", statement)
        self.emit(
            EventType.STATEMENT_GENERATED,
            {
                "statement_id": statement_id,
                "loan_id": loan_id,
                "outstanding": outstanding,
                "total_paid": total_paid,
            },
            correlation_id=event.correlation_id,
        )

    def __on_collection_updated(self, event: Event) -> None:
        """Record a collection update trigger for statement generation.

        Args:
            event: The COLLECTION_UPDATED event.
        """
        loan_id = event.payload.get("loan_id", "")
        if loan_id:
            self.store.set(
                f"stmt_trigger:{loan_id}:{self.__clock.iso()}",
                {
                    "loan_id": loan_id,
                    "trigger": "collection_update",
                },
            )

    def __on_payment_received_trigger(self, event: Event) -> None:
        """Record a payment received trigger for statement generation.

        Args:
            event: The PAYMENT_RECEIVED event.
        """
        loan_id = event.payload.get("loan_id", "")
        if loan_id:
            self.store.set(
                f"stmt_trigger:{loan_id}:{self.__clock.iso()}",
                {
                    "loan_id": loan_id,
                    "trigger": "payment",
                },
            )
