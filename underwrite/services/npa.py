# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""NPA tracking — RBI-mandated asset classification, provisioning, and DLG triggers.

Extends the base NPA service with:
  - SMA (Special Mention Account) classification (SMA-0, SMA-1, SMA-2)
  - RBI provisioning percentage computation per bucket
  - Income recognition suspension for NPA accounts
  - Configurable DLG trigger threshold
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
from underwrite.store import StoreBackend
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator

NPA_STANDARD_MAX_DAYS: int = 90
NPA_SUBSTANDARD_MAX_DAYS: int = 180
NPA_DOUBTFUL_MAX_DAYS: int = 360
SMA0_MAX_DAYS: int = 30
SMA1_MAX_DAYS: int = 60
SMA2_MAX_DAYS: int = 90
DLG_TRIGGER_DAYS_DEFAULT: int = 120
NPA_DAYS_DEFAULT: int = 90
STANDARD_PROVISIONING_RATE_DEFAULT: float = 0.0025
SUBSTANDARD_PROVISIONING_RATE_DEFAULT: float = 0.15
DOUBTFUL_PROVISIONING_RATE_DEFAULT: float = 0.25
LOSS_PROVISIONING_RATE_DEFAULT: float = 1.0


class Handler(StatefulService):
    """Tracks days-past-due and transitions accounts through SMA/NPA buckets.

    SMA (Special Mention Account) buckets per RBI:
      - SMA-0:  1-30 days overdue
      - SMA-1: 31-60 days overdue
      - SMA-2: 61-90 days overdue

    NPA (Non-Performing Asset) buckets per RBI Master Circular:
      - Standard:    0-90 days
      - Substandard: 91-180 days
      - Doubtful:    181-360 days
      - Loss:        >360 days

    Provisioning rates (configurable via NpaConfig):
      - Standard assets:  0.25%
      - Substandard:     15%
      - Doubtful:        25% (secured portion)
      - Loss:           100%
    """

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: StoreBackend,
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
        """Initialize the NPA service with provisioning rates and DLG config."""
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
        self.accounts: dict[str, dict[str, Any]] = {}
        self.loan_borrowers: dict[str, str] = {}
        self.trigger_days: int = kwargs.get("dlg_trigger_days", DLG_TRIGGER_DAYS_DEFAULT)
        self.npa_days: int = kwargs.get("npa_days", NPA_DAYS_DEFAULT)
        self.provisioning_rates: dict[str, float] = {
            "standard": kwargs.get("standard_provisioning_rate", STANDARD_PROVISIONING_RATE_DEFAULT),
            "substandard": kwargs.get("substandard_provisioning_rate", SUBSTANDARD_PROVISIONING_RATE_DEFAULT),
            "doubtful": kwargs.get("doubtful_provisioning_rate_secured", DOUBTFUL_PROVISIONING_RATE_DEFAULT),
            "loss": kwargs.get("loss_provisioning_rate", LOSS_PROVISIONING_RATE_DEFAULT),
        }
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("accounts", dict)

    def start(self) -> None:
        """Load persisted NPA accounts when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.accounts = loaded
            self.loan_borrowers = {
                record["loan_id"]: borrower for borrower, record in loaded.items() if record.get("loan_id")
            }

    def handle(self, event: Message) -> None:
        """Process loan-originated and default-occurred events.

        Args:
            event: The incoming domain event.
        """
        with self.state_lock:
            if event.event_type == Type.LOAN_ORIGINATED:
                borrower: str = PayloadValidator().non_empty(event.payload, "borrower")
                principal: float = PayloadValidator().finite(event.payload, "principal", 0.0)
                loan_id: str = event.payload.get("loan_id", "")
                self.accounts[borrower] = {
                    "originated_at": self.clock.iso(),
                    "days_overdue": 0,
                    "dlg_invoked": False,
                    "principal": principal,
                    "outstanding": principal,
                    "bucket": "standard",
                    "provisioning_rate": 0.0,
                    "provisioning_amount": 0.0,
                    "income_suspended": False,
                }
                if loan_id:
                    self.accounts[borrower]["loan_id"] = loan_id
                    self.loan_borrowers[loan_id] = borrower
                self.sync()
            elif event.event_type == Type.DEFAULT_OCCURRED:
                borrower = event.payload.get("borrower", "")
                if not borrower:
                    logger.warning("dropping DEFAULT_OCCURRED with missing borrower")
                    return
                record = self.accounts.get(borrower)
                if record is None:
                    return
                days: int = record.get("days_overdue", self.trigger_days)
                event_principal: float = PayloadValidator().finite(event.payload, "principal", 0.0)
                self.classify_and_provision(borrower, record, days, event.correlation_id, event_principal)
            elif event.event_type == Type.PAYMENT_OVERDUE:
                self.on_payment_overdue(event)

    def mark_overdue(self, borrower: str, days: int) -> None:
        """Update the days-past-due counter for a borrower.

        Args:
            borrower: The borrower identifier.
            days: Number of days past due to record.
        """
        with self.state_lock:
            if borrower in self.accounts:
                self.accounts[borrower]["days_overdue"] = days
                self.sync()

    def on_payment_overdue(self, event: Message) -> None:
        """Resolve the borrower for an overdue payment and classify the account.

        ``PAYMENT_OVERDUE`` events are keyed by ``loan_id`` while the
        NPA ledger is keyed by ``borrower``; the loan->borrower map is
        populated from ``LOAN_ORIGINATED`` so overdue schedules can be
        attributed to the correct account.

        Args:
            event: The PAYMENT_OVERDUE event with loan_id, due_date,
                and amount payload.
        """
        loan_id: str = event.payload.get("loan_id", "")
        if not loan_id:
            logger.warning("dropping PAYMENT_OVERDUE with missing loan_id")
            return
        borrower: str = self.loan_borrowers.get(loan_id, loan_id)
        record = self.accounts.get(borrower)
        if record is None:
            logger.debug("no NPA account for loan {} (borrower {})", loan_id, borrower)
            return
        days: int = int(record.get("days_overdue", 0))
        due_str: str = event.payload.get("due_date", "")
        if due_str:
            try:
                due = datetime.fromisoformat(str(due_str))
                overdue = max(0, (self.clock.utc_now() - due).days)
                days = max(days, overdue)
            except (ValueError, TypeError):
                logger.debug("invalid due_date {} on PAYMENT_OVERDUE for loan {}", due_str, loan_id)
        self.mark_overdue(borrower, days)
        event_principal: float = PayloadValidator().finite(event.payload, "amount", 0.0)
        self.classify_and_provision(borrower, record, days, event.correlation_id, event_principal)

    def classify_and_provision(
        self,
        borrower: str,
        record: dict[str, Any],
        days: int,
        correlation_id: str,
        event_principal: float = 0.0,
    ) -> None:
        """Classify account, compute provisioning, and check DLG trigger.

        Args:
            borrower: The borrower identifier.
            record: The account record dict.
            days: Number of days past due.
            correlation_id: Correlation ID for emitted events.
            event_principal: Principal from the event payload.
        """
        bucket: str = self.classify_overdue_days(days)

        sma_bucket = self.sma_classify(days)
        if sma_bucket:
            self.emit(
                Type.SMA_CLASSIFIED,
                {
                    "borrower": borrower,
                    "sma_bucket": sma_bucket,
                    "days_overdue": days,
                },
                correlation_id=correlation_id,
            )

        record["bucket"] = bucket
        record["days_overdue"] = days

        rate = self.provisioning_rates.get(bucket, 0.0)
        outstanding = record.get("outstanding", record.get("principal", event_principal or 0.0))
        provisioning_amount = round(outstanding * rate, 2)

        self.emit(
            Type.PROVISIONING_COMPUTED,
            {
                "borrower": borrower,
                "bucket": bucket,
                "outstanding": outstanding,
                "provisioning_rate": rate,
                "provisioning_amount": provisioning_amount,
            },
            correlation_id=correlation_id,
        )

        record["provisioning_rate"] = rate
        record["provisioning_amount"] = provisioning_amount

        if bucket in ("substandard", "doubtful", "loss") and not record.get("income_suspended", False):
            record["income_suspended"] = True
            record["income_suspended_at"] = self.clock.iso()
            self.emit(
                Type.INCOME_RECOGNITION_SUSPENDED,
                {
                    "borrower": borrower,
                    "bucket": bucket,
                    "days_overdue": days,
                },
                correlation_id=correlation_id,
            )

        self.emit(
            Type.NPA_BUCKET_CHANGED,
            {
                "borrower": borrower,
                "bucket": bucket,
            },
            correlation_id=correlation_id,
        )

        should_trigger_dlg: bool = days >= self.trigger_days and not record.get("dlg_invoked", False)
        if should_trigger_dlg:
            record["dlg_invoked"] = True
            self.sync()
            self.emit(
                Type.DLG_TRIGGERED,
                {
                    "loan_id": borrower,
                    "recovery_amount": event_principal or outstanding,
                },
                correlation_id=correlation_id,
            )

        self.sync()

    def sync(self) -> None:
        """Persist the current NPA accounts to the store."""
        self.repo.save(self.accounts)

    @staticmethod
    def classify_overdue_days(days: int) -> str:
        """Classify days-past-due into RBI NPA bucket.

        Per RBI norms an asset becomes NPA on the 91st day past due;
        we therefore treat ``days >= 90`` as substandard (NPA),
        ``>= 180`` as doubtful, and ``>= 360`` as loss.

        Args:
            days: Number of days past due.

        Returns:
            NPA bucket name: standard, substandard, doubtful, or loss.
        """
        if days < 0:
            raise ValueError(f"days must be non-negative (got {days})")
        if days < NPA_STANDARD_MAX_DAYS:
            return "standard"
        if days < NPA_SUBSTANDARD_MAX_DAYS:
            return "substandard"
        if days < NPA_DOUBTFUL_MAX_DAYS:
            return "doubtful"
        return "loss"

    @staticmethod
    def sma_classify(days: int) -> str:
        """Classify days-past-due into SMA bucket.

        Args:
            days: Number of days past due.

        Returns:
            SMA bucket name (sma_0, sma_1, sma_2) or empty string
            if outside SMA range.
        """
        if days <= 0:
            return ""
        if days <= SMA0_MAX_DAYS:
            return "sma_0"
        if days <= SMA1_MAX_DAYS:
            return "sma_1"
        if days <= SMA2_MAX_DAYS:
            return "sma_2"
        return ""
