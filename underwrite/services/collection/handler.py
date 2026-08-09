"""Collection - tracks repayment schedule and overdue accounts.

Listens for loan.originated and repaid events to maintain an
amortization schedule and flag overdue accounts. Uses the Indian
amortization engine (underwrite.__amortization__) for accurate
EMI-based schedules.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from underwrite.__amortization__ import generate_schedule
from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.__metrics__ import SystemClock
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

class CollectionHandler(StatefulService):
    """Tracks repayment schedules and flags overdue accounts.

    Uses the full EMI amortization schedule from
    underwrite.__amortization__ for accurate repayment tracking,
    supporting both the standard EMI formula and custom EMI overrides.
    """

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
        **kwargs: Any,
    ) -> None:
        """Initialize the collection service with loan tracking.

        Args:
            **kwargs: Forwarded to StatefulService.__init__.

        """
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
        self.__loans: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("loans", dict)
        loaded = self.repo.load(default={})
        if loaded:
            self.__loans = loaded

    def handle(self, event: Event) -> None:
        """Process loan origination and repayment events.

        Args:
            event: The incoming domain event.

        """
        if event.event_type == EventType.LOAN_ORIGINATED:
            self.on_loan_originated(event)
        elif event.event_type == EventType.REPAID:
            self.on_repaid(event)

    def on_loan_originated(self, event: Event) -> None:
        """Create a collection record with amortization schedule."""
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = max(0.0, get_finite(p, "principal", 0.0))
        term: int = max(1, int(get_finite(p, "term", 1.0)))
        annual_rate: float = get_finite(p, "annual_rate", 0.0)
        if not math.isfinite(annual_rate) or annual_rate < 0:
            annual_rate = 0.0
        start_date_str: str = p.get("start_date", "")

        with self.state_lock:
            if annual_rate > 0 and term > 0:
                sched = self.__build_schedule(principal, annual_rate, term, start_date_str)
                monthly = float(sched.emi)
            else:
                monthly = principal / term if term > 0 else 0.0
            loan_record = {
                "principal": principal,
                "term": term,
                "annual_rate": annual_rate,
                "monthly": monthly,
                "paid": 0.0,
                "status": "active",
                "created_at": self.__clock.iso(),
            }
            if annual_rate > 0:
                loan_record["schedule"] = sched.to_dict()
            self.__loans[borrower] = loan_record
            self.repo.save(self.__loans)

        self.emit(
            EventType.COLLECTION_UPDATED,
            {
                "borrower": borrower,
                "monthly": monthly,
                "total": principal,
                "status": "active",
            },
            correlation_id=event.correlation_id,
        )

    def on_repaid(self, event: Event) -> None:
        """Apply a repayment to the borrower's loan."""
        p = event.payload
        borrower: str = p.get("borrower", "") or p.get("user", "")
        if not borrower:
            logger.debug("repaid event missing borrower/user, ignored")
            return
        delta: float = get_finite(p, "delta_earned")
        emit_data: dict[str, Any] | None = None
        with self.state_lock:
            loan = self.__loans.get(borrower)
            if loan:
                loan["paid"] += delta
                if loan["paid"] >= loan["principal"]:
                    loan["status"] = "closed"
                self.repo.save(self.__loans)
                emit_data = {
                    "borrower": borrower,
                    "paid": round(loan["paid"], 2),
                    "remaining": round(loan["principal"] - loan["paid"], 2),
                    "status": loan["status"],
                }
        if emit_data is not None:
            self.emit(
                EventType.COLLECTION_UPDATED,
                emit_data,
                correlation_id=event.correlation_id,
            )

    def get(self, borrower: str) -> dict[str, Any] | None:
        """Retrieve the collection record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Collection record dict or None if not found.

        """
        with self.state_lock:
            return self.__loans.get(borrower)

    @staticmethod
    def __build_schedule(
        principal: float,
        annual_rate: float,
        term: int,
        start_date_str: str = "",
    ) -> Any:
        """Build an amortization schedule for the loan.

        Args:
            principal: Loan principal.
            annual_rate: Annual interest rate in percent.
            term: Loan tenure in months.
            start_date_str: Optional ISO start date string.

        Returns:
            An AmortizationSchedule instance.

        """
        sd: date | None = None
        if start_date_str:
            try:
                sd = date.fromisoformat(start_date_str)
            except (ValueError, TypeError):
                sd = None
        return generate_schedule(
            Decimal(str(principal)),
            Decimal(str(annual_rate)),
            term,
            start_date=sd,
        )
