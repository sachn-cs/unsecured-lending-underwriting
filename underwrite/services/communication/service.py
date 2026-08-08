"""Communication dispatch service.

Sends notifications through configured channels (email, SMS, push).
In serverless mode this delegates to a cloud function. Emits
communication.sent on successful dispatch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.services.base import NanoService


class CommunicationService(NanoService):
    """Dispatches outbound messages through configured channels.

    In production, each channel (email / SMS / push) is backed by a
    cloud function or third-party API. This service logs the dispatch
    and emits communication.sent.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the communication service and register event handlers.

        Args:
            **kwargs: Forwarded to NanoService.__init__.

        """
        super().__init__(**kwargs)
        self.handlers: dict[str, Any] = {
            EventType.COMMUNICATION_SEND: self.__on_communication_send,
            EventType.STATEMENT_GENERATED: self.__on_statement_generated,
        }

    def handle(self, event: Event) -> None:
        """Dispatch an outbound communication.

        Args:
            event: The incoming event. Only COMMUNICATION_SEND and
                STATEMENT_GENERATED events are processed.

        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_communication_send(self, event: Event) -> None:
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
        message_id: str = (
            f"msg_{recipient}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:8]}"
        )
        msg = {
            "recipient": recipient,
            "subject": subject,
            "channel": channel,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        # Dispatch through the configured channel. The base class
        # does not actually deliver mail/SMS; this service records
        # intent and emits a SENT event only after a successful
        # delivery attempt via __dispatch_channel. Without a
        # delivery adapter the service is essentially a log of
        # outbound communications; mark the message as
        # queued rather than sent.
        delivery_status = self.__dispatch_channel(channel, recipient, subject)
        self.store.set(f"message:{message_id}", {**msg, "delivery_status": delivery_status})
        if delivery_status == "sent":
            self.emit(
                EventType.COMMUNICATION_SENT,
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

    def __dispatch_channel(self, channel: str, recipient: str, subject: str) -> str:
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

    def __on_statement_generated(self, event: Event) -> None:
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
