"""Collateral management - LTV tracking, marking, and liquidation."""

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


class CollateralHandler(StatefulService):
    """Tracks posted collateral against active loans and triggers liquidation on default."""

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
        """Initialize the collateral service with LTV tracking.

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
        self.__ltv_ratio: float = 0.75
        self.__collateral: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("collateral", dict)

    def start(self) -> None:
        """Load persisted collateral state when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.__collateral = loaded

    def handle(self, event: Event) -> None:
        """Process loan origination and default events against collateral.

        Args:
            event: The incoming domain event.

        """
        if event.event_type == EventType.LOAN_ORIGINATED:
            self.on_loan_originated(event)
        elif event.event_type == EventType.DEFAULT_OCCURRED:
            self.on_default(event)

    def on_loan_originated(self, event: Event) -> None:
        """Set collateral requirements for a new loan.

        Args:
            event: The loan origination event with borrower and
                principal payload.

        """
        borrower: str = get_non_empty(event.payload, "borrower")
        principal: float = get_finite(event.payload, "principal")
        required: float = principal * self.__ltv_ratio
        with self.state_lock:
            self.__collateral[borrower] = {
                "principal": principal,
                "required": required,
                "posted": 0.0,
                "ltv": self.__ltv_ratio,
                "created_at": self.__clock.iso(),
            }
            self.repo.save(self.__collateral)
        self.emit(
            EventType.COLLATERAL_MARKED,
            {
                "borrower": borrower,
                "required": required,
                "ltv_ratio": self.__ltv_ratio,
            },
            correlation_id=event.correlation_id,
        )

    def on_default(self, event: Event) -> None:
        """Liquidate collateral on default.

        Args:
            event: The default event containing the borrower identifier.

        """
        borrower = event.payload.get("borrower", "")
        if not borrower:
            logger.warning("dropping DEFAULT_OCCURRED with missing borrower")
            return
        with self.state_lock:
            col = self.__collateral.pop(borrower, None)
            if col:
                try:
                    self.repo.save(self.__collateral)
                except Exception:
                    logger.exception(
                        "failed to persist collateral removal for {}, restoring in-memory state",
                        borrower,
                    )
                    self.__collateral[borrower] = col
                    raise
        if col:
            self.emit(
                EventType.COLLATERAL_LIQUIDATED,
                {
                    "borrower": borrower,
                    "principal": col["principal"],
                    "required": col["required"],
                },
                correlation_id=event.correlation_id,
            )

    def get(self, borrower: str) -> dict[str, Any] | None:
        """Retrieve collateral record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Collateral record dict or None if not found.

        """
        with self.state_lock:
            return self.__collateral.get(borrower)
