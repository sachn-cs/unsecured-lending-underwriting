"""Document — generates and manages loan document references.

Listens for ``underwriter.approved`` events, creates document records,
and emits ``document.generated``.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty


class DocumentService(NanoService):
    """Generates loan document references after approval."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__documents: dict[str, list[dict[str, Any]]] = {}
        self.__load_store()

    def handle(self, event: Event) -> None:
        with self.__lock:
            if event.event_type != EventType.UNDERWRITER_APPROVED:
                return
            p = event.payload
            borrower: str = get_non_empty(p, "borrower")
            principal: float = get_finite(p, "principal")
            doc_id: str = str(uuid.uuid4())[:8]

            record = {
                "doc_id": doc_id,
                "borrower": borrower,
                "principal": principal,
                "status": "generated",
            }
            self.__documents.setdefault(borrower, []).append(record)
            self.__sync_store()

            self.emit(EventType.DOCUMENT_GENERATED, {
                "borrower": borrower,
                "principal": principal,
                "doc_id": doc_id,
            },
                      correlation_id=event.correlation_id)

    def documents_for(self, borrower: str) -> list[dict[str, Any]]:
        """Retrieve all documents generated for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            List of document records for the borrower.
        """
        with self.__lock:
            return list(self.__documents.get(borrower, []))

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        """Restore document records from the store, if present."""
        with self.__lock:
            raw = self.store.get(f"{self.service_id}:documents")
            if raw is not None and isinstance(raw, dict):
                self.__documents = dict(raw)

    def __sync_store(self) -> None:
        """Persist the current document records to the store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:documents",
                           dict(self.__documents))
