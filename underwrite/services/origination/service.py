"""Loan origination service.

Handles the intake, validation, and submission of loan applications.
Emits ``origination.created`` when a new application is started and
``origination.submitted`` when the application is ready for review.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService
from underwrite.validate import get_finite

logger = logging.getLogger(__name__)


class OriginationService(NanoService):
    """Manages loan application lifecycle: creation, validation, submission."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__applications: dict[str, dict[str, Any]] = {}
        self.__load_store()

    def handle(self, event: Event) -> None:
        with self.__lock:
            if event.event_type == EventType.ORIGINATION_CREATE:
                borrower: str = event.payload.get("borrower", "")
                principal: float = get_finite(event.payload, "principal", 0.0)
                if not borrower or principal <= 0:
                    logger.warning(
                        "dropping ORIGINATION_CREATE with missing borrower or principal"
                    )
                    return
                application_id: str = f"app_{borrower}_{int(datetime.now(timezone.utc).timestamp())}"
                app_record = {
                    "borrower": borrower,
                    "principal": principal,
                    "status": "created",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self.store.set(f"origination:{application_id}", app_record)
                self.__applications[
                    f"origination:{application_id}"] = app_record
                self.__sync_store()
                self.emit(EventType.ORIGINATION_CREATED, {
                    "application_id": application_id,
                    "borrower": borrower,
                    "principal": principal,
                },
                          correlation_id=event.correlation_id)

            elif event.event_type == EventType.ORIGINATION_SUBMIT:
                application_id = event.payload.get("application_id", "")
                record = self.store.get(f"origination:{application_id}")
                if record and record.get("status") == "created":
                    record["status"] = "submitted"
                    record["submitted_at"] = datetime.now(
                        timezone.utc).isoformat()
                    self.store.set(f"origination:{application_id}", record)
                    self.__applications[f"origination:{application_id}"] = dict(
                        record)
                    self.__sync_store()
                    self.emit(EventType.ORIGINATION_SUBMITTED, {
                        "application_id": application_id,
                        "borrower": record["borrower"],
                        "principal": record["principal"],
                    },
                              correlation_id=event.correlation_id)

    # -- state persistence ---------------------------------------------------

    def __load_store(self) -> None:
        """Restore application records from the store, if present."""
        with self.__lock:
            raw = self.store.get(f"{self.service_id}:applications")
            if raw is not None and isinstance(raw, dict):
                self.__applications = dict(raw)

    def __sync_store(self) -> None:
        """Persist the current application records to the store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:applications",
                           dict(self.__applications))
