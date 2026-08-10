"""Keypair management - key registration and rotation."""

from __future__ import annotations

from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.services.base import Core
from underwrite.validate import PayloadValidator


class Handler(Core):
    """Manages nano-service identities: registration and key rotation."""

    def handle(self, event: Message) -> None:
        """Process identity registration and rotation events.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == Type.IDENTITY_REGISTER:
            self.register(event)
        elif event.event_type == Type.IDENTITY_ROTATE:
            self.rotate(event)

    def register(self, event: Message) -> None:
        """Register a new service identity.

        Args:
            event: The identity registration event.
        """
        service_id: str = PayloadValidator().non_empty(event.payload, "name")
        identity: Keypair = Keypair.create(service_id)
        self.store.set(
            f"identity:{service_id}",
            {
                "name": service_id,
                "public_key": identity.public_key,
            },
        )
        self.emit(
            Type.IDENTITY_REGISTERED,
            {
                "name": service_id,
                "public_key": identity.public_key,
            },
            correlation_id=event.correlation_id,
        )

    def rotate(self, event: Message) -> None:
        """Rotate the key for an existing service identity.

        Args:
            event: The identity rotation event.
        """
        service_id = PayloadValidator().non_empty(event.payload, "name")
        with self.state_lock:
            existing = self.store.get(f"identity:{service_id}")
            if not existing:
                logger.warning("identity rotation requested for unknown service {!r}", service_id)
                return
            identity = Keypair.create(service_id)
            self.store.set(
                f"identity:{service_id}",
                {
                    "name": service_id,
                    "public_key": identity.public_key,
                },
            )
        self.emit(
            Type.IDENTITY_ROTATED,
            {
                "name": service_id,
                "public_key": identity.public_key,
            },
            correlation_id=event.correlation_id,
        )
