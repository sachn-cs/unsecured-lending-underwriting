"""Identity management - key registration and rotation."""

from __future__ import annotations

import threading
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__identity__ import Identity
from underwrite.__logger__ import logger
from underwrite.services import NanoService
from underwrite.validate import get_non_empty


class IdentityService(NanoService):
    """Manages nano-service identities: registration and key rotation."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the identity service with a reentrant lock."""
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()

    def handle(self, event: Event) -> None:
        """Process identity registration and rotation events.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == EventType.IDENTITY_REGISTER:
            self.register(event)
        elif event.event_type == EventType.IDENTITY_ROTATE:
            self.rotate(event)

    def register(self, event: Event) -> None:
        """Register a new service identity.

        Args:
            event: The identity registration event.
        """
        service_id: str = get_non_empty(event.payload, "service_id")
        identity: Identity = Identity.create(service_id)
        self.store.set(
            f"identity:{service_id}",
            {
                "service_id": service_id,
                "public_key": identity.public_key,
            },
        )
        self.emit(
            EventType.IDENTITY_REGISTERED,
            {
                "service_id": service_id,
                "public_key": identity.public_key,
            },
            correlation_id=event.correlation_id,
        )

    def rotate(self, event: Event) -> None:
        """Rotate the key for an existing service identity.

        Args:
            event: The identity rotation event.
        """
        service_id = get_non_empty(event.payload, "service_id")
        with self.__lock:
            existing = self.store.get(f"identity:{service_id}")
            if not existing:
                logger.warning("identity rotation requested for unknown service {!r}", service_id)
                return
            identity = Identity.create(service_id)
            self.store.set(
                f"identity:{service_id}",
                {
                    "service_id": service_id,
                    "public_key": identity.public_key,
                },
            )
        self.emit(
            EventType.IDENTITY_ROTATED,
            {
                "service_id": service_id,
                "public_key": identity.public_key,
            },
            correlation_id=event.correlation_id,
        )
