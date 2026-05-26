"""Communication dispatch service.

Sends notifications through configured channels (email, SMS, push).
In serverless mode this delegates to a cloud function.  Emits
``communication.sent`` on successful dispatch.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService

logger = logging.getLogger(__name__)


class CommunicationService(NanoService):
    """Dispatches outbound messages through configured channels.

    In production, each channel (email / SMS / push) is backed by a
    cloud function or third-party API.  This service logs the dispatch
    and emits ``communication.sent``.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__messages: dict[str, dict[str, Any]] = {}
        self.__load_store()

    def handle(self, event: Event) -> None:
        with self.__lock:
            if event.event_type == EventType.COMMUNICATION_SEND:
                recipient: str = event.payload.get("recipient", "")
                subject: str = event.payload.get("subject", "")
                channel: str = event.payload.get("channel", "email")
                if not recipient:
                    logger.warning("dropping COMMUNICATION_SEND with missing recipient")
                    return
                message_id: str = f"msg_{recipient}_{int(datetime.now(timezone.utc).timestamp())}"
                msg = {
                    "recipient": recipient,
                    "subject": subject,
                    "channel": channel,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                }
                self.store.set(f"message:{message_id}", msg)
                self.__messages[f"message:{message_id}"] = msg
                self.__sync_store()
                self.emit(EventType.COMMUNICATION_SENT, {
                    "message_id": message_id,
                    "recipient": recipient,
                    "channel": channel,
                    "subject": subject,
                },
                          correlation_id=event.correlation_id)

            elif event.event_type == EventType.DOCUMENT_GENERATED:
                loan_id: str = event.payload.get("loan_id", "")
                doc_type: str = event.payload.get("type", "")
                if not loan_id or not doc_type:
                    logger.warning("dropping DOCUMENT_GENERATED with missing loan_id or type")
                    return
                doc_notification = {
                    "loan_id": loan_id,
                    "type": doc_type,
                    "notified": True,
                    "notified_at": datetime.now(timezone.utc).isoformat(),
                }
                self.store.set(f"comm_doc:{loan_id}:{doc_type}", doc_notification)
                self.__messages[f"comm_doc:{loan_id}:{doc_type}"] = doc_notification
                self.__sync_store()

            elif event.event_type == EventType.STATEMENT_GENERATED:
                loan_id = event.payload.get("loan_id", "")
                if loan_id:
                    stmt_key = f"comm_stmt:{loan_id}:{datetime.now(timezone.utc).isoformat()}"
                    stmt_notification = {
                        "loan_id": loan_id,
                        "notified": True,
                    }
                    self.store.set(stmt_key, stmt_notification)
                    self.__messages[stmt_key] = stmt_notification
                    self.__sync_store()

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        """Restore message records from the store, if present."""
        with self.__lock:
            raw = self.store.get(f"{self.service_id}:messages")
            if raw is not None and isinstance(raw, dict):
                self.__messages = dict(raw)

    def __sync_store(self) -> None:
        """Persist the current message records to the store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:messages", dict(self.__messages))
