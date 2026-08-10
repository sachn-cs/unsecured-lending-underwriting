# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Collateral management - LTV tracking, marking, and liquidation."""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.local import LocalBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store, InMemory, Disk, Sqlite
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator


class Handler(StatefulService):
    """Tracks posted collateral against active loans and triggers liquidation on default."""

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
        """Initialize the collateral service with LTV tracking.

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
        self.ltv_ratio: float = 0.75
        self.collateral: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, dict[str, Any]]] = self.store_repo("collateral", dict)

    def start(self) -> None:
        """Load persisted collateral state when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.collateral = loaded

    def handle(self, event: Message) -> None:
        """Process loan origination and default events against collateral.

        Args:
            event: The incoming domain event.

        """
        if event.event_type == Type.LOAN_ORIGINATED:
            self.on_loan_originated(event)
        elif event.event_type == Type.DEFAULT_OCCURRED:
            self.on_default(event)

    def on_loan_originated(self, event: Message) -> None:
        """Set collateral requirements for a new loan.

        Args:
            event: The loan origination event with borrower and
                principal payload.

        """
        borrower: str = PayloadValidator().non_empty(event.payload, "borrower")
        principal: float = PayloadValidator().finite(event.payload, "principal")
        required: float = principal * self.ltv_ratio
        with self.state_lock:
            self.collateral[borrower] = {
                "principal": principal,
                "required": required,
                "posted": 0.0,
                "ltv": self.ltv_ratio,
                "created_at": self.clock.iso(),
            }
            self.repo.save(self.collateral)
        self.emit(
            Type.COLLATERAL_MARKED,
            {
                "borrower": borrower,
                "required": required,
                "ltv_ratio": self.ltv_ratio,
            },
            correlation_id=event.correlation_id,
        )

    def on_default(self, event: Message) -> None:
        """Liquidate collateral on default.

        Args:
            event: The default event containing the borrower identifier.

        """
        borrower = event.payload.get("borrower", "")
        if not borrower:
            logger.warning("dropping DEFAULT_OCCURRED with missing borrower")
            return
        with self.state_lock:
            col = self.collateral.pop(borrower, None)
            if col:
                try:
                    self.repo.save(self.collateral)
                except Exception:
                    logger.exception(
                        "failed to persist collateral removal for {}, restoring in-memory state",
                        borrower,
                    )
                    self.collateral[borrower] = col
                    raise
        if col:
            self.emit(
                Type.COLLATERAL_LIQUIDATED,
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
            return self.collateral.get(borrower)
