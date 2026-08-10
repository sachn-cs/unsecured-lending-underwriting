# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Fee assessment service.

Calculates and tracks fees: late payment fees, origination fees,
prepayment penalties, service charges, and penal interest.
Emits fee.assessed when a fee is applied to a loan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.local import LocalBus
from underwrite.constants import MONEY_QUANTUM
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import BatchedStoreRepository
from underwrite.store import Store, InMemory, Disk, Sqlite
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator
from underwrite.value_objects import IdGenerator

DEFAULT_FEE_SCHEDULES: dict[str, float] = {
    "late_payment": 25.0,
    "origination": 0.01,
    "prepayment": 0.005,
    "service": 5.0,
}

MAX_FEE_PER_LOAN: float = 1000.0


@dataclass(frozen=True, slots=True)
class FeeConfig:
    """Typed configuration for Handler.

    Replaces the previous ``kwargs.pop("penal_interest_daily_rate", ...)``
    pattern: callers now pass a FeeConfig (or its fields are extracted
    from kwargs via a constructor that does not mutate the caller's
    mapping).
    """

    fee_schedules: dict[str, float] = field(default_factory=lambda: DEFAULT_FEE_SCHEDULES)
    penal_interest_daily_rate: float = 0.0
    late_payment_percent: float = 0.0
    max_penal_interest_per_loan: float = 0.0


class Handler(StatefulService):
    """Manages fee assessment, tracking, and lifecycle.

    Supports Indian lending fee structures:
      - Flat late payment fee (per overdue event)
      - Percentage-based late fee (late_payment_percent of overdue EMI)
      - Daily penal interest on overdue principal
      - Origination fee (percentage of principal)
      - Prepayment penalty (percentage of outstanding)
    """

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: Store | InMemory | Disk | Sqlite,
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
        config = FeeConfig(
            fee_schedules=kwargs.pop("fee_schedules", DEFAULT_FEE_SCHEDULES),
            penal_interest_daily_rate=kwargs.pop("penal_interest_daily_rate", 0.0),
            late_payment_percent=kwargs.pop("late_payment_percent", 0.0),
            max_penal_interest_per_loan=kwargs.pop("max_penal_interest_per_loan", 0.0),
        )
        self.schedules: dict[str, float] = config.fee_schedules
        self.penal_daily_rate: float = config.penal_interest_daily_rate
        self.late_percent: float = config.late_payment_percent
        self.max_penal: float = config.max_penal_interest_per_loan
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
        self.fees: dict[str, dict[str, Any]] = {}
        self.repo: BatchedStoreRepository[dict[str, dict[str, Any]]] = self.batched_repo("fees", dict, sync_interval=10)
        self.id_generator: IdGenerator = IdGenerator()

    def start(self) -> None:
        """Load persisted fee records when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.fees = loaded

    def assess(
        self,
        loan_id: str,
        fee_type: str,
        principal: float = 0.0,
        overdue_days: int = 0,
        overdue_amount: float = 0.0,
        correlation_id: str = "",
    ) -> None:
        """Assess a fee and persist it.

        Args:
            loan_id: Target loan identifier.
            fee_type: Type of fee to assess.
            principal: Loan principal (for origination fees).
            overdue_days: Days past due (for penal interest).
            overdue_amount: Overdue amount (for percentage-based fees).
            correlation_id: Correlation ID for tracing.
        """
        with self.state_lock:
            if not loan_id:
                logger.warning("fee.assess missing loan_id, ignored")
                return

            principal = max(0.0, principal)

            total_assessed = sum(r.get("amount", 0.0) for r in self.fees.values() if r.get("loan_id", "") == loan_id)
            if total_assessed >= MAX_FEE_PER_LOAN:
                logger.warning(
                    "fee cap reached for loan {} (total {:.2f} >= {:.2f}), skipping fee assessment",
                    loan_id,
                    total_assessed,
                    MAX_FEE_PER_LOAN,
                )
                return

            amount = self.compute_amount(fee_type, principal, overdue_days, overdue_amount)
            if amount <= 0:
                logger.debug("zero/negative fee amount {} for loan {}, skipped", amount, loan_id)
                return

            fee_id: str = f"fee_{loan_id}_{fee_type}_{self.id_generator.next()}"
            amount_dec: Decimal = Decimal(str(amount)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            fee_record = {
                "fee_id": fee_id,
                "loan_id": loan_id,
                "fee_type": fee_type,
                "amount": float(amount_dec),
                "amount_decimal": str(amount_dec),
                "assessed_at": datetime.now(timezone.utc).isoformat(),
                "paid": False,
            }
            self.store.set(f"fee:{fee_id}", fee_record)
            self.fees[f"fee:{fee_id}"] = fee_record
            self.repo.incr_and_maybe_sync(self.fees)
            self.emit(
                Type.FEE_ASSESSED,
                {
                    "fee_id": fee_id,
                    "loan_id": loan_id,
                    "fee_type": fee_type,
                    "amount": float(amount_dec),
                    "amount_decimal": str(amount_dec),
                },
                correlation_id=correlation_id,
            )

    def compute_amount(self, fee_type: str, principal: float, overdue_days: int, overdue_amount: float) -> float:
        """Compute the fee amount based on type and parameters.

        Args:
            fee_type: Type of fee.
            principal: Loan principal.
            overdue_days: Days past due.
            overdue_amount: Amount overdue.

        Returns:
            Computed fee amount.
        """
        if fee_type == "origination":
            return principal * self.schedules.get("origination", 0.0)
        if fee_type == "prepayment":
            return self.schedules.get("prepayment", 0.0)
        if fee_type == "late_payment":
            return self.schedules.get("late_payment", 0.0)
        if fee_type == "late_payment_percent":
            return overdue_amount * self.late_percent / 100.0
        if fee_type == "penal_interest":
            daily = self.penal_daily_rate / 100.0
            penal = overdue_amount * daily * overdue_days
            if self.max_penal > 0 and penal > self.max_penal:
                penal = self.max_penal
            return penal
        if fee_type == "service":
            return self.schedules.get("service", 0.0)
        return 0.0

    def handle(self, event: Message) -> None:
        """Assess and pay fees based on incoming events.

        Args:
            event: The incoming event.
        """
        if event.event_type == Type.FEE_ASSESS:
            self.assess(
                loan_id=event.payload.get("loan_id", ""),
                fee_type=event.payload.get("fee_type", ""),
                principal=PayloadValidator().finite(event.payload, "principal", 0.0),
                overdue_days=event.payload.get("overdue_days", 0),
                overdue_amount=event.payload.get("overdue_amount", 0.0),
                correlation_id=event.correlation_id,
            )

        elif event.event_type == Type.FEE_PAY:
            fee_id = event.payload.get("fee_id", "")
            with self.state_lock:
                record = self.store.get(f"fee:{fee_id}")
                if record and not record["paid"]:
                    record["paid"] = True
                    record["paid_at"] = datetime.now(timezone.utc).isoformat()
                    self.store.set(f"fee:{fee_id}", record)
                    self.fees[f"fee:{fee_id}"] = record.copy()
                    self.repo.incr_and_maybe_sync(self.fees)

        elif event.event_type == Type.PAYMENT_OVERDUE:
            loan_id = event.payload.get("loan_id", "")
            if not loan_id:
                logger.warning("PAYMENT_OVERDUE missing loan_id, skipped")
                return
            existing = self.store.keys(f"fee:fee_{loan_id}_late_payment")
            if existing:
                logger.debug("late_payment fee already assessed for loan {}, skipping", loan_id)
                return
            self.assess(
                loan_id=loan_id,
                fee_type="late_payment",
                correlation_id=event.correlation_id,
            )

    def health_check(self) -> dict[str, Any]:
        """Fee-specific health: reports total fee count and pending fees."""
        with self.state_lock:
            if not self.fees:
                return {**super().health_check(), "fee_count": 0, "pending_fees": 0}
            pending = sum(1 for r in self.fees.values() if not r.get("paid", False))
            return {
                **super().health_check(),
                "fee_count": len(self.fees),
                "pending_fees": pending,
            }
