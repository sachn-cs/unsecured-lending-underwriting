# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Communication dispatch service.

Sends notifications through configured channels (email, SMS, push).
In serverless mode this delegates to a cloud function. Emits
communication.sent on successful dispatch.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
from underwrite.store import StoreBackend
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.value_objects import IdGenerator


class Handler(Core):
    """Dispatches outbound messages through configured channels.

    In production, each channel (email / SMS / push) is backed by a
    cloud function or third-party API. This service logs the dispatch
    and emits communication.sent.
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
        """Initialize the communication service and register event handlers.

        Args:
            **kwargs: Forwarded to Core.__init__.

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
        self.id_generator: IdGenerator = IdGenerator()
        self.handlers: dict[str, Any] = {
            Type.COMMUNICATION_SEND: self.on_communication_send,
            Type.STATEMENT_GENERATED: self.on_statement_generated,
        }

    def handle(self, event: Message) -> None:
        """Dispatch an outbound communication.

        Args:
            event: The incoming event. Only COMMUNICATION_SEND and
                STATEMENT_GENERATED events are processed.

        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def on_communication_send(self, event: Message) -> None:
        """Send a communication via the configured channel.

        Args:
            event: The communication send event with recipient,
                subject, and channel payload.

        """
        recipient: str = event.payload.get("recipient", "")
        subject: str = event.payload.get("subject", "")
        channel: str = event.payload.get("channel", "email")
        if not recipient:
            logger.warning("dropping COMMUNICATION_SEND with missing recipient")
            return
        message_id: str = f"msg_{recipient}_{self.clock.now():.0f}_{self.id_generator.next()}"
        msg = {
            "recipient": recipient,
            "subject": subject,
            "channel": channel,
            "sent_at": self.clock.iso(),
        }
        delivery_status = self.dispatch_channel(channel, recipient, subject)
        self.store.set(f"message:{message_id}", {**msg, "delivery_status": delivery_status})
        if delivery_status == "sent":
            self.emit(
                Type.COMMUNICATION_SENT,
                {
                    "message_id": message_id,
                    "recipient": recipient,
                    "channel": channel,
                    "subject": subject,
                },
                correlation_id=event.correlation_id,
            )
        else:
            logger.info(
                "communication {} queued for {} via {} (status={})",
                message_id,
                recipient,
                channel,
                delivery_status,
            )

    def dispatch_channel(self, channel: str, recipient: str, subject: str) -> str:
        """Hook for actually delivering the message through a channel.

        Subclasses or production deployments can override this to
        integrate with an SMS/email provider. The base implementation
        records the intent in the local store only — the message is
        *queued*, not *sent*. Callers should not emit COMMUNICATION_SENT
        for queued messages; downstream consumers may treat SENT as
        proof of delivery.

        Returns:
            One of ``"sent"``, ``"queued"``, ``"unsupported"``, or
            ``"failed"``.
        """
        return "queued"

    def on_statement_generated(self, event: Message) -> None:
        """Record that a statement notification was sent.

        Args:
            event: The statement generated event containing loan_id.

        """
        loan_id = event.payload.get("loan_id", "")
        if loan_id:
            stmt_key = f"comm_stmt:{loan_id}:{datetime.now(timezone.utc).isoformat()}"
            self.store.set(
                stmt_key,
                {
                    "loan_id": loan_id,
                    "notified": True,
                },
            )
