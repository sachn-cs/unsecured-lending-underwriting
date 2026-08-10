# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Loan origination service.

Handles the intake, validation, and submission of loan applications.
Emits ``origination.created`` when a new application is started and
``origination.submitted`` when the application is ready for review.
"""

from __future__ import annotations

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
from underwrite.services.base import Core, Dependencies
from underwrite.store import Disk, InMemory, Sqlite, Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator
from underwrite.value_objects import IdGenerator


class Handler(Core):
    """Manages loan application lifecycle: creation, validation, submission."""

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
        """Initialize the origination service."""
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
        self.id_generator: IdGenerator = IdGenerator()
        self.clock: SystemClock = SystemClock()
        self.handlers: dict[str, Any] = {
            Type.ORIGINATION_CREATE: self.on_create,
            Type.ORIGINATION_SUBMIT: self.on_submit,
        }

    def handle(self, event: Message) -> None:
        """Process an origination event.

        Args:
            event: The incoming origination event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def on_create(self, event: Message) -> None:
        """Handle an origination create request.

        Args:
            event: The ORIGINATION_CREATE event.
        """
        borrower: str = event.payload.get("borrower", "")
        principal: float = PayloadValidator().finite(event.payload, "principal", 0.0)
        if not borrower or principal <= 0:
            logger.warning("dropping ORIGINATION_CREATE with missing borrower or principal")
            return
        application_id: str = f"app_{borrower}_{self.id_generator.next()}"
        app_record = {
            "borrower": borrower,
            "principal": principal,
            "status": "created",
            "created_at": self.clock.iso(),
        }
        self.store.set(f"origination:{application_id}", app_record)
        self.emit(
            Type.ORIGINATION_CREATED,
            {
                "application_id": application_id,
                "borrower": borrower,
                "principal": principal,
            },
            correlation_id=event.correlation_id,
        )

    def on_submit(self, event: Message) -> None:
        """Handle an origination submit request.

        Args:
            event: The ORIGINATION_SUBMIT event.
        """
        application_id = event.payload.get("application_id", "")
        with self.state_lock:
            record = self.store.get(f"origination:{application_id}")
            if not record or record.get("status") != "created":
                return
            record["status"] = "submitted"
            record["submitted_at"] = self.clock.iso()
            self.store.set(f"origination:{application_id}", record)
        self.emit(
            Type.ORIGINATION_SUBMITTED,
            {
                "application_id": application_id,
                "borrower": record["borrower"],
                "principal": record["principal"],
            },
            correlation_id=event.correlation_id,
        )
