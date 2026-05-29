"""Ed25519 identity management for nano-service attestation.

Each service signs every emitted event so downstream consumers can
verify provenance.  Keys support automatic rotation with TTL.
"""

from __future__ import annotations

__all__ = [
    "HAS_CRYPTO",
    "Identity",
    "KeyRotationManager",
]

import base64
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from underwrite.__exceptions__ import IdentityError

logger = logging.getLogger(__name__)

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    HAS_CRYPTO: bool = True
except ImportError:
    HAS_CRYPTO = False


@dataclass(frozen=True)
class Identity:
    """An Ed25519 keypair that identifies a nano service.

    The public key is included in every emitted event; downstream
    consumers use it to verify the event signature.
    """

    service_id: str
    public_key: str
    __private_key: str = ""
    created_at: float = 0.0

    @classmethod
    def create(cls,
               service_id: str,
               private_key_pem: str = "",
               secrets_manager: Any | None = None) -> Identity:
        """Creates or derives an identity.

        Args:
            service_id: Unique name for this service.
            private_key_pem: Optional PEM-encoded private key.
            secrets_manager: Optional SecretsManager to load the key from.

        Returns:
            A new Identity instance.
        """
        if not private_key_pem and secrets_manager is not None:
            loaded = secrets_manager.load_private_key(service_id)
            if loaded:
                private_key_pem = loaded
        now = time.time()
        if private_key_pem:
            private = serialization.load_pem_private_key(
                private_key_pem.encode("utf-8") if isinstance(
                    private_key_pem, str) else private_key_pem,
                password=None,
            )
            if not isinstance(private, ed25519.Ed25519PrivateKey):
                raise IdentityError("key must be Ed25519")
            public = private.public_key()
            identity = cls(
                service_id=service_id,
                public_key=base64.b64encode(
                    public.public_bytes(
                        encoding=serialization.Encoding.Raw,
                        format=serialization.PublicFormat.Raw,
                    )).decode(),
                created_at=now,
            )
            object.__setattr__(
                identity, '_Identity__private_key',
                base64.b64encode(
                    private.private_bytes(
                        encoding=serialization.Encoding.Raw,
                        format=serialization.PrivateFormat.Raw,
                        encryption_algorithm=serialization.NoEncryption(),
                    )).decode())
            return identity
        if not HAS_CRYPTO:
            logger.warning(
                "cryptography library not available — using dummy "
                "identity for %s; signatures are NOT secure", service_id)
            dummy = b"\x00" * 32
            identity = cls(
                service_id=service_id,
                public_key=base64.b64encode(dummy).decode(),
                created_at=now,
            )
            object.__setattr__(identity, '_Identity__private_key',
                               base64.b64encode(dummy).decode())
            return identity
        private = ed25519.Ed25519PrivateKey.generate()
        public = private.public_key()
        identity = cls(
            service_id=service_id,
            public_key=base64.b64encode(
                public.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )).decode(),
            created_at=now,
        )
        object.__setattr__(
            identity, '_Identity__private_key',
            base64.b64encode(
                private.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption(),
                )).decode())
        return identity

    def sign(self, payload: str) -> str:
        """Signs a string payload and returns a base64-encoded signature."""
        if not HAS_CRYPTO:
            return f"dummy_{payload[:16]}"
        private_bytes = base64.b64decode(self.__private_key)
        private = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
        return base64.b64encode(private.sign(payload.encode("utf-8"))).decode()

    def verify(self, payload: str, signature: str) -> bool:
        """Verifies a base64-encoded signature against a payload."""
        if not HAS_CRYPTO:
            return signature.startswith("dummy_")
        try:
            public_bytes = base64.b64decode(self.public_key)
            public = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
            public.verify(base64.b64decode(signature), payload.encode("utf-8"))
            return True
        except InvalidSignature:
            return False

    def attest(self, transaction: dict[str, Any]) -> dict[str, Any]:
        """Returns a copy of *transaction* with provenance metadata appended."""
        payload = json.dumps(transaction, sort_keys=True)
        return {
            **transaction,
            "attested_by": self.service_id,
            "attested_key": self.public_key,
            "attested_sig": self.sign(payload),
            "attested_at": datetime.now(timezone.utc).isoformat(),
        }


class KeyRotationManager:
    """Manages automatic key rotation for services.

    Keys are rotated after a configurable TTL.  Old keys are retained
    for a grace period so in-flight signatures can still be verified.
    """

    def __init__(self,
                 ttl_seconds: float = 86400.0,
                 grace_period: float = 3600.0) -> None:
        """Initialises a key-rotation manager.

        Args:
            ttl_seconds: Time-to-live for each key before rotation.
            grace_period: Extra time old keys are retained for verification.
        """
        self.__lock: threading.RLock = threading.RLock()
        self.__ttl: float = ttl_seconds
        self.__grace: float = grace_period
        self.__current: dict[str, Identity] = {}
        self.__previous: dict[str, Identity] = {}

    def get_or_create(self, service_id: str) -> Identity:
        """Returns the current identity for a service, rotating if TTL expired.

        Args:
            service_id: Service identifier.

        Returns:
            A valid Identity (possibly freshly rotated).
        """
        with self.__lock:
            now = time.time()
            identity = self.__current.get(service_id)
            if identity and (now - identity.created_at) < self.__ttl:
                return identity
            return self.__rotate_locked(service_id)

    def rotate(self, service_id: str) -> Identity:
        """Force-rotates the identity for a service.

        Args:
            service_id: Service identifier.

        Returns:
            The new Identity.
        """
        with self.__lock:
            return self.__rotate_locked(service_id)

    def __rotate_locked(self, service_id: str) -> Identity:
        old = self.__current.get(service_id)
        if old:
            self.__previous[service_id] = old
        new_identity = Identity.create(service_id)
        self.__current[service_id] = new_identity
        return new_identity

    def verify_with_rotation(self, payload: str, signature: str,
                             service_id: str, public_key: str) -> bool:
        """Verifies a signature against current or previous (grace) keys.

        Args:
            payload: The signed payload string.
            signature: Base64-encoded signature.
            service_id: Expected service identifier.
            public_key: Base64-encoded public key to verify against.

        Returns:
            True if the signature is valid under any recognised key.
        """
        with self.__lock:
            identity = self.__current.get(service_id)
            if identity and identity.public_key == public_key:
                return identity.verify(payload, signature)
            prev = self.__previous.get(service_id)
            if prev:
                now = time.time()
                if (now - prev.created_at) < self.__grace:
                    return prev.verify(payload, signature)
            return False
