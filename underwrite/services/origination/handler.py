"""Loan origination service.

Handles the intake, validation, and submission of loan applications.
Emits ``origination.created`` when a new application is started and
``origination.submitted`` when the application is ready for review.
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.__metrics__ import SystemClock
from underwrite.__value_objects__ import IdGenerator
from underwrite.services.base import NanoService
from underwrite.validate import get_finite


class OriginationHandler(NanoService):
    """Manages loan application lifecycle: creation, validation, submission."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the origination service."""
        super().__init__(**kwargs)
        self.__id_generator: IdGenerator = IdGenerator()
        self.__clock: SystemClock = SystemClock()
        self.handlers: dict[str, Any] = {
            EventType.ORIGINATION_CREATE: self.__on_create,
            EventType.ORIGINATION_SUBMIT: self.__on_submit,
        }

    def handle(self, event: Event) -> None:
        """Process an origination event.

        Args:
            event: The incoming origination event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_create(self, event: Event) -> None:
        """Handle an origination create request.

        Args:
            event: The ORIGINATION_CREATE event.
        """
        borrower: str = event.payload.get("borrower", "")
        principal: float = get_finite(event.payload, "principal", 0.0)
        if not borrower or principal <= 0:
            logger.warning("dropping ORIGINATION_CREATE with missing borrower or principal")
            return
        application_id: str = f"app_{borrower}_{self.__id_generator.next()}"
        app_record = {
            "borrower": borrower,
            "principal": principal,
            "status": "created",
            "created_at": self.__clock.iso(),
        }
        self.store.set(f"origination:{application_id}", app_record)
        self.emit(
            EventType.ORIGINATION_CREATED,
            {
                "application_id": application_id,
                "borrower": borrower,
                "principal": principal,
            },
            correlation_id=event.correlation_id,
        )

    def __on_submit(self, event: Event) -> None:
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
            record["submitted_at"] = self.__clock.iso()
            self.store.set(f"origination:{application_id}", record)
        self.emit(
            EventType.ORIGINATION_SUBMITTED,
            {
                "application_id": application_id,
                "borrower": record["borrower"],
                "principal": record["principal"],
            },
            correlation_id=event.correlation_id,
        )
