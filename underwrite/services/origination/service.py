"""Loan origination service.

Handles the intake, validation, and submission of loan applications.
Emits ``origination.created`` when a new application is started and
``origination.submitted`` when the application is ready for review.
"""

from __future__ import annotations

from datetime import datetime, timezone

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService


class OriginationService(NanoService):
    """Manages loan application lifecycle: creation, validation, submission."""

    def handle(self, event: Event) -> None:
        if event.event_type == "origination.create":
            borrower: str = event.payload.get("borrower", "")
            principal: float = float(event.payload.get("principal", 0))
            if not borrower or principal <= 0:
                return
            application_id: str = f"app_{borrower}_{int(datetime.now(timezone.utc).timestamp())}"
            self.store.set(
                f"origination:{application_id}", {
                    "borrower": borrower,
                    "principal": principal,
                    "status": "created",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            self.emit(EventType.ORIGINATION_CREATED, {
                "application_id": application_id,
                "borrower": borrower,
                "principal": principal,
            },
                      correlation_id=event.correlation_id)

        elif event.event_type == "origination.submit":
            application_id = event.payload.get("application_id", "")
            record = self.store.get(f"origination:{application_id}")
            if record and record.get("status") == "created":
                record["status"] = "submitted"
                record["submitted_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"origination:{application_id}", record)
                self.emit(EventType.ORIGINATION_SUBMITTED, {
                    "application_id": application_id,
                    "borrower": record["borrower"],
                    "principal": record["principal"],
                },
                          correlation_id=event.correlation_id)
