"""Identity management — key registration and rotation."""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.__identity__ import Identity
from underwrite.services import NanoService
from underwrite.validate import get_non_empty


class IdentityService(NanoService):
    """Manages nano-service identities: registration and key rotation."""

    def handle(self, event: Event) -> None:
        if event.event_type == "identity_register":
            service_id: str = get_non_empty(event.payload, "service_id")
            identity: Identity = Identity.create(service_id)
            self.store.set(f"identity:{service_id}", {
                "service_id": service_id,
                "public_key": identity.public_key,
            })
            self.emit(EventType.IDENTITY_REGISTERED, {
                "service_id": service_id,
                "public_key": identity.public_key,
            },
                      correlation_id=event.correlation_id)
        elif event.event_type == "identity_rotate":
            service_id = get_non_empty(event.payload, "service_id")
            identity = Identity.create(service_id)
            self.store.set(f"identity:{service_id}", {
                "service_id": service_id,
                "public_key": identity.public_key,
            })
            self.emit(EventType.IDENTITY_ROTATED, {
                "service_id": service_id,
                "public_key": identity.public_key,
            },
                      correlation_id=event.correlation_id)
