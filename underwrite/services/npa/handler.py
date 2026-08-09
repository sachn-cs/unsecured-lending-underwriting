"""NPA tracking — RBI-mandated asset classification, provisioning, and DLG triggers.

Extends the base NPA service with:
  - SMA (Special Mention Account) classification (SMA-0, SMA-1, SMA-2)
  - RBI provisioning percentage computation per bucket
  - Income recognition suspension for NPA accounts
  - Configurable DLG trigger threshold
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


class NPAHandler(StatefulService):
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
        """Initialize the NPA service with provisioning rates and DLG config."""
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
        self.__accounts: dict[str, dict[str, Any]] = {}
        self.__trigger_days: int = kwargs.get("dlg_trigger_days", DLG_TRIGGER_DAYS_DEFAULT)
        self.__npa_days: int = kwargs.get("npa_days", NPA_DAYS_DEFAULT)
        self.__provisioning_rates: dict[str, float] = {
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
            self.__accounts = loaded

    def handle(self, event: Event) -> None:
        """Process loan-originated and default-occurred events.

        Args:
            event: The incoming domain event.
        """
        with self.state_lock:
            if event.event_type == EventType.LOAN_ORIGINATED:
                borrower: str = get_non_empty(event.payload, "borrower")
                principal: float = get_finite(event.payload, "principal", 0.0)
                self.__accounts[borrower] = {
                    "originated_at": self.__clock.iso(),
                    "days_overdue": 0,
                    "dlg_invoked": False,
                    "principal": principal,
                    "outstanding": principal,
                    "bucket": "standard",
                    "provisioning_rate": 0.0,
                    "provisioning_amount": 0.0,
                    "income_suspended": False,
                }
                self.__sync()
            elif event.event_type == EventType.DEFAULT_OCCURRED:
                borrower = event.payload.get("borrower", "")
                if not borrower:
                    logger.warning("dropping DEFAULT_OCCURRED with missing borrower")
                    return
                record = self.__accounts.get(borrower)
                if record is None:
                    return
                days: int = record.get("days_overdue", self.__trigger_days)
                event_principal: float = get_finite(event.payload, "principal", 0.0)
                self.classify_and_provision(borrower, record, days, event.correlation_id, event_principal)

    def mark_overdue(self, borrower: str, days: int) -> None:
        """Update the days-past-due counter for a borrower.

        Args:
            borrower: The borrower identifier.
            days: Number of days past due to record.
        """
        with self.state_lock:
            if borrower in self.__accounts:
                self.__accounts[borrower]["days_overdue"] = days
                self.__sync()

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
                EventType.SMA_CLASSIFIED,
                {
                    "borrower": borrower,
                    "sma_bucket": sma_bucket,
                    "days_overdue": days,
                },
                correlation_id=correlation_id,
            )

        record["bucket"] = bucket
        record["days_overdue"] = days

        rate = self.__provisioning_rates.get(bucket, 0.0)
        outstanding = record.get("outstanding", record.get("principal", event_principal or 0.0))
        provisioning_amount = round(outstanding * rate, 2)

        self.emit(
            EventType.PROVISIONING_COMPUTED,
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
            record["income_suspended_at"] = self.__clock.iso()
            self.emit(
                EventType.INCOME_RECOGNITION_SUSPENDED,
                {
                    "borrower": borrower,
                    "bucket": bucket,
                    "days_overdue": days,
                },
                correlation_id=correlation_id,
            )

        self.emit(
            EventType.NPA_BUCKET_CHANGED,
            {
                "borrower": borrower,
                "bucket": bucket,
            },
            correlation_id=correlation_id,
        )

        should_trigger_dlg: bool = days >= self.__trigger_days and not record.get("dlg_invoked", False)
        if should_trigger_dlg:
            record["dlg_invoked"] = True
            self.__sync()
            self.emit(
                EventType.DLG_TRIGGERED,
                {
                    "loan_id": borrower,
                    "recovery_amount": event_principal or outstanding,
                },
                correlation_id=correlation_id,
            )

        self.__sync()

    def __sync(self) -> None:
        """Persist the current NPA accounts to the store."""
        self.repo.save(self.__accounts)

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
