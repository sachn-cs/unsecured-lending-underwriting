"""Recovery workflows — post-default recovery orchestration.

Implements a multi-stage recovery process with store-backed persistence:
  1. NEGOTIATION — offer is sent (stage recorded)
  2. PAYMENT_PLAN — tracked when payments arrive
  3. ESCALATION — flagged if too many offers rejected
  4. SETTLEMENT — recovery completed or loss recognized

State is persisted via the Store backend (MemoryStore, FileStore, or
PostgresStore) so in-flight recoveries survive service restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
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

DEFAULT_RECOVERY_RATE: float = 0.3
NEGOTIATION_DAYS: int = 30
ESCALATION_THRESHOLD: int = 3


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    """Typed configuration for RecoveryHandler.

    Replaces the previous ``kwargs.pop("recovery_rate", ...)`` pattern:
    callers now pass a RecoveryConfig (or its fields are extracted
    from kwargs via a constructor that does not mutate the caller's
    mapping).
    """

    recovery_rate: float = DEFAULT_RECOVERY_RATE
    negotiation_days: int = NEGOTIATION_DAYS
    escalation_threshold: int = ESCALATION_THRESHOLD


class RecoveryStage(str, Enum):
    """Stages of the recovery workflow."""

    NEGOTIATION = "negotiation"
    PAYMENT_PLAN = "payment_plan"
    ESCALATION = "escalation"
    SETTLEMENT = "settlement"


class RecoveryHandler(StatefulService):
    """Orchestrates multi-stage recovery after a default event.

    State is persisted to the store so in-flight recoveries survive
    restarts.  Reacts to DEFAULT_OCCURRED, PAYMENT_RECEIVED, and
    offer response events to drive recovery forward.
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
        """Initialize the recovery service.

        Args:
            recovery_rate: Fraction of principal offered in recovery.
            negotiation_days: Days allowed for negotiation.
            escalation_threshold: Number of rejected offers before escalation.
        """
        config = RecoveryConfig(
            recovery_rate=kwargs.pop("recovery_rate", DEFAULT_RECOVERY_RATE),
            negotiation_days=kwargs.pop("negotiation_days", NEGOTIATION_DAYS),
            escalation_threshold=kwargs.pop("escalation_threshold", ESCALATION_THRESHOLD),
        )
        self.__recovery_rate: float = config.recovery_rate
        self.__negotiation_days: int = config.negotiation_days
        self.__escalation_threshold: int = config.escalation_threshold
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
        self.__recoveries: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("recoveries", dict)

    def start(self) -> None:
        """Load persisted recovery state when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.__recoveries = loaded
            active = sum(1 for r in self.__recoveries.values() if r.get("stage") != RecoveryStage.SETTLEMENT.value)
            if active > 0:
                logger.info(
                    "loaded {} active recovery(s) from store",
                    active,
                )

    def handle(self, event: Event) -> None:
        """Process events that drive the recovery workflow.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == EventType.DEFAULT_OCCURRED:
            self.__start_recovery(event)
        elif event.event_type == EventType.PAYMENT_RECEIVED:
            self.__on_payment_received(event)
        elif event.event_type == "recovery.offer_response":
            self.__on_offer_response(event)

    def __start_recovery(self, event: Event) -> None:
        """Start a new recovery workflow for a defaulted borrower.

        Args:
            event: The DEFAULT_OCCURRED event.
        """
        borrower: str = get_non_empty(event.payload, "borrower")
        principal: float = get_finite(event.payload, "principal")

        with self.state_lock:
            if borrower in self.__recoveries:
                logger.warning("recovery already active for {}, skipping", borrower)
                return

            recovery: dict[str, Any] = {
                "borrower": borrower,
                "principal": principal,
                "stage": RecoveryStage.NEGOTIATION.value,
                "started_at": self.__clock.iso(),
                "offer_count": 0,
                "plan_failures": 0,
                "recovered": 0.0,
                "last_action": self.__clock.iso(),
            }
            self.__recoveries[borrower] = recovery
            self.__sync()

        logger.info("recovery started for {} (principal={:.2f})", borrower, principal)
        self.emit(
            EventType.RECOVERY_STARTED,
            {
                "borrower": borrower,
                "principal": principal,
                "stage": RecoveryStage.NEGOTIATION.value,
                "started_at": recovery["started_at"],
            },
            correlation_id=event.correlation_id,
        )

        offer_amount: float = principal * self.__recovery_rate
        with self.state_lock:
            recovery["offer_count"] += 1
            recovery["last_action"] = self.__clock.iso()
            self.__sync()

        self.emit(
            "recovery.offer",
            {
                "borrower": borrower,
                "offer_amount": offer_amount,
                "due_by": (self.__clock.utc_now() + timedelta(days=self.__negotiation_days)).isoformat(),
                "stage": RecoveryStage.NEGOTIATION.value,
            },
            correlation_id=event.correlation_id,
        )

    def __on_offer_response(self, event: Event) -> None:
        """Handle a borrower's response to a recovery offer.

        Args:
            event: The recovery.offer_response event.
        """
        borrower: str = get_non_empty(event.payload, "borrower")
        accepted: bool = event.payload.get("accepted", False)

        with self.state_lock:
            recovery = self.__recoveries.get(borrower)
            if not recovery:
                return
            if recovery["stage"] in (
                RecoveryStage.ESCALATION.value,
                RecoveryStage.SETTLEMENT.value,
            ):
                return

            if accepted:
                recovery["stage"] = RecoveryStage.PAYMENT_PLAN.value
                recovery["last_action"] = self.__clock.iso()
                self.__sync()
                logger.info("recovery offer accepted for {}", borrower)
                self.emit(
                    EventType.RECOVERY_STARTED,
                    {
                        "borrower": borrower,
                        "principal": recovery["principal"],
                        "stage": RecoveryStage.PAYMENT_PLAN.value,
                        "message": "payment plan agreed",
                    },
                    correlation_id=event.correlation_id,
                )
            else:
                recovery["offer_count"] += 1
                if recovery["offer_count"] >= self.__escalation_threshold:
                    recovery["stage"] = RecoveryStage.ESCALATION.value
                    recovery["last_action"] = self.__clock.iso()
                    self.__sync()
                    logger.warning("recovery escalated for {}", borrower)
                    self.emit(
                        "recovery.escalated",
                        {
                            "borrower": borrower,
                            "principal": recovery["principal"],
                            "stage": RecoveryStage.ESCALATION.value,
                        },
                        correlation_id=event.correlation_id,
                    )
                else:
                    recovery["last_action"] = self.__clock.iso()
                    self.__sync()
                    offer_amount = recovery["principal"] * self.__recovery_rate
                    self.emit(
                        "recovery.offer",
                        {
                            "borrower": borrower,
                            "offer_amount": offer_amount,
                            "due_by": (self.__clock.utc_now() + timedelta(days=self.__negotiation_days)).isoformat(),
                            "stage": RecoveryStage.NEGOTIATION.value,
                        },
                        correlation_id=event.correlation_id,
                    )

    def __on_payment_received(self, event: Event) -> None:
        """Track a payment received during recovery.

        Args:
            event: The PAYMENT_RECEIVED event.
        """
        borrower: str = get_non_empty(event.payload, "borrower")
        amount: float = get_finite(event.payload, "amount")

        with self.state_lock:
            recovery = self.__recoveries.get(borrower)
            if not recovery:
                return
            if recovery["stage"] == RecoveryStage.SETTLEMENT.value:
                return

            recovery["recovered"] += amount
            recovery["last_action"] = self.__clock.iso()
            outstanding: float = recovery["principal"] - recovery["recovered"]

            if outstanding <= 0:
                recovery["stage"] = RecoveryStage.SETTLEMENT.value
                self.__sync()
                logger.info(
                    "recovery completed for {} (recovered={:.2f})",
                    borrower,
                    recovery["recovered"],
                )
                self.emit(
                    EventType.RECOVERY_COMPLETED,
                    {
                        "borrower": borrower,
                        "recovered": recovery["recovered"],
                        "outstanding": 0.0,
                        "stage": RecoveryStage.SETTLEMENT.value,
                    },
                    correlation_id=event.correlation_id,
                )
            else:
                self.__sync()
                logger.info(
                    "recovery progress for {}: recovered={:.2f} outstanding={:.2f}",
                    borrower,
                    recovery["recovered"],
                    outstanding,
                )
                self.emit(
                    "recovery.progress",
                    {
                        "borrower": borrower,
                        "recovered": recovery["recovered"],
                        "outstanding": outstanding,
                        "stage": recovery["stage"],
                    },
                    correlation_id=event.correlation_id,
                )

    def get_recovery(self, borrower: str) -> dict[str, Any] | None:
        """Return the current recovery record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Recovery dict or None if not found.
        """
        with self.state_lock:
            return self.__recoveries.get(borrower)

    def health_check(self) -> dict[str, Any]:
        """Return health metrics including recovery counts.

        Returns:
            Dict with base health info plus recovery stats.
        """
        base = super().health_check()
        with self.state_lock:
            active = sum(1 for r in self.__recoveries.values() if r.get("stage") != RecoveryStage.SETTLEMENT.value)
            base["active_recoveries"] = active
            base["total_recoveries"] = len(self.__recoveries)
        return base

    def __sync(self) -> None:
        """Persist recoveries to the store."""
        self.repo.save(self.__recoveries)
