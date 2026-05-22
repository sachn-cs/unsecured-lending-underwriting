"""Disbursement — processes loan payout after document generation.

Listens for ``document.generated`` events and emits
``disbursement.processed``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty


class DisbursementService(NanoService):
    """Processes loan disbursement to borrower accounts."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__disbursements: dict[str, dict[str, Any]] = {}

    def handle(self, event: Event) -> None:
        if event.event_type != EventType.DOCUMENT_GENERATED:
            return
        p = event.payload
        borrower: str = get_non_empty(p, "borrower")
        principal: float = get_finite(p, "principal")
        doc_id: str = p.get("doc_id", "")

        record = {
            "borrower": borrower,
            "principal": principal,
            "doc_id": doc_id,
            "disbursed_at": datetime.now(timezone.utc).isoformat(),
            "status": "disbursed",
        }
        self.__disbursements[borrower] = record

        self.emit(EventType.DISBURSEMENT_PROCESSED, {
            "borrower": borrower,
            "principal": principal,
            "doc_id": doc_id,
        },
                  correlation_id=event.correlation_id)

    def get(self, borrower: str) -> dict[str, Any] | None:
        """Retrieve the disbursement record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Disbursement record dict or None if not yet disbursed.
        """
        return self.__disbursements.get(borrower)
