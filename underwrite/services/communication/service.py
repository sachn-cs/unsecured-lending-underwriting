"""Communication dispatch service.

Sends notifications through configured channels (email, SMS, push).
In serverless mode this delegates to a cloud function.  Emits
``communication.sent`` on successful dispatch.
"""

from __future__ import annotations

from datetime import datetime, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService


class CommunicationService(NanoService):
    """Dispatches outbound messages through configured channels.

    In production, each channel (email / SMS / push) is backed by a
    cloud function or third-party API.  This service logs the dispatch
    and emits ``communication.sent``.
    """

    def handle(self, event: Event) -> None:
        if event.event_type == "communication.send":
            recipient: str = event.payload.get("recipient", "")
            subject: str = event.payload.get("subject", "")
            channel: str = event.payload.get("channel", "email")
            if not recipient:
                return
            message_id: str = f"msg_{recipient}_{int(datetime.now(timezone.utc).timestamp())}"
            self.store.set(
                f"message:{message_id}", {
                    "recipient": recipient,
                    "subject": subject,
                    "channel": channel,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                })
            self.emit("communication.sent", {
                "message_id": message_id,
                "recipient": recipient,
                "channel": channel,
                "subject": subject,
            },
                      correlation_id=event.correlation_id)

        elif event.event_type == EventType.DOCUMENT_GENERATED:
            loan_id: str = event.payload.get("loan_id", "")
            doc_type: str = event.payload.get("type", "")
            if loan_id and doc_type:
                self.store.set(
                    f"comm_doc:{loan_id}:{doc_type}", {
                        "loan_id": loan_id,
                        "type": doc_type,
                        "notified": True,
                        "notified_at": datetime.now(timezone.utc).isoformat(),
                    })

        elif event.event_type == EventType.STATEMENT_GENERATED:
            loan_id = event.payload.get("loan_id", "")
            if loan_id:
                self.store.set(
                    f"comm_stmt:{loan_id}:{datetime.now(timezone.utc).isoformat()}",
                    {
                        "loan_id": loan_id,
                        "notified": True,
                    })
