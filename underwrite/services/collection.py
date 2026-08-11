# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Collection - tracks repayment schedule and overdue accounts.

Listens for loan.originated and repaid events to maintain an
amortization schedule and flag overdue accounts. Uses the Indian
amortization engine (underwrite.amortization) for accurate
EMI-based schedules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from underwrite.amortization import generate_schedule
from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Sqlite, Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator


class Handler(StatefulService):
    """Tracks repayment schedules and flags overdue accounts.

    Uses the full EMI amortization schedule from
    underwrite.amortization for accurate repayment tracking,
    supporting both the standard EMI formula and custom EMI overrides.
    """

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
        **kwargs: Any,
    ) -> None:
        """Initialize the collection service with loan tracking.

        Args:
            **kwargs: Forwarded to StatefulService.__init__.

        """
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
        self.clock: SystemClock = SystemClock()
        self.loans: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("loans", dict)
        loaded = self.repo.load(default={})
        if loaded:
            self.loans = loaded

    def handle(self, event: Message) -> None:
        """Process loan origination and repayment events.

        Args:
            event: The incoming domain event.

        """
        if event.event_type == Type.LOAN_ORIGINATED:
            self.on_loan_originated(event)
        elif event.event_type == Type.REPAID:
            self.on_repaid(event)

    def on_loan_originated(self, event: Message) -> None:
        """Create a collection record with amortization schedule."""
        p = event.payload
        borrower: str = PayloadValidator().non_empty(p, "borrower")
        principal: float = max(0.0, PayloadValidator().finite(p, "principal", 0.0))
        term: int = max(1, int(PayloadValidator().finite(p, "term", 1.0)))
        annual_rate: float = max(0.0, PayloadValidator().finite(p, "annual_rate", 0.0))
        start_date_str: str = p.get("start_date", "")

        with self.state_lock:
            if annual_rate > 0 and term > 0:
                sched = self.build_schedule(principal, annual_rate, term, start_date_str)
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
                "created_at": self.clock.iso(),
            }
            if annual_rate > 0:
                loan_record["schedule"] = sched.to_dict()
            self.loans[borrower] = loan_record
            self.repo.save(self.loans)

        self.emit(
            Type.COLLECTION_UPDATED,
            {
                "borrower": borrower,
                "monthly": monthly,
                "total": principal,
                "status": "active",
            },
            correlation_id=event.correlation_id,
        )

    def on_repaid(self, event: Message) -> None:
        """Apply a repayment to the borrower's loan."""
        p = event.payload
        borrower: str = p.get("borrower", "") or p.get("user", "")
        if not borrower:
            logger.debug("repaid event missing borrower/user, ignored")
            return
        delta: float = PayloadValidator().finite(p, "delta_earned")
        emit_data: dict[str, Any] | None = None
        with self.state_lock:
            loan = self.loans.get(borrower)
            if loan:
                loan["paid"] += delta
                if loan["paid"] >= loan["principal"]:
                    loan["status"] = "closed"
                self.repo.save(self.loans)
                emit_data = {
                    "borrower": borrower,
                    "paid": round(loan["paid"], 2),
                    "remaining": round(loan["principal"] - loan["paid"], 2),
                    "status": loan["status"],
                }
        if emit_data is not None:
            self.emit(
                Type.COLLECTION_UPDATED,
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
            return self.loans.get(borrower)

    @staticmethod
    def build_schedule(
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
