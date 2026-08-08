"""Ed25519 identity management for nano-service attestation.

Each service signs every emitted event so downstream consumers can
verify provenance.
"""

from __future__ import annotations

__all__ = [
    "Identity",
]

import base64
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from underwrite.__exceptions__ import IdentityError


class PrivateKeyBackend(Protocol):
    """Minimal contract for persisting Ed25519 private keys at rest."""

    def load_private_key(self, service_id: str) -> str | None: ...
    def store_private_key(self, service_id: str, pem: str) -> None: ...


@dataclass(frozen=True)
class Identity:
    """An Ed25519 keypair that identifies a nano service.

    The public key is included in every emitted event; downstream
    consumers use it to verify the event signature.

    When *encryption_passphrase* is provided the private key is stored
    encrypted at rest (PKCS8 — ``BestAvailableEncryption``) to reduce
    the risk of key material leaking in memory dumps / core dumps.
    """

    service_id: str
    public_key: str
    __private_key: str = ""
    encrypted: bool = False
    created_at: float = 0.0
    __sign_lock: threading.Lock = threading.Lock()

    @classmethod
    def create(
        cls,
        service_id: str,
        private_key_pem: str = "",
        secrets_manager: PrivateKeyBackend | None = None,
        encryption_passphrase: str | None = None,
    ) -> Identity:
        """Creates or derives an identity.

        Args:
            service_id: Unique name for this service.
            private_key_pem: Optional PEM-encoded private key.
            secrets_manager: Optional SecretsManager. When provided, the
                private key is loaded from the configured backend on
                startup and any newly generated key is persisted, so
                the same key survives process restarts.
            encryption_passphrase: If set, the private key is encrypted at
                rest in memory using this passphrase.

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
                private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem,
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
                    )
                ).decode(),
                encrypted=encryption_passphrase is not None,
                created_at=now,
            )
            pass_bytes = encryption_passphrase.encode() if encryption_passphrase else None
            alg = serialization.BestAvailableEncryption(pass_bytes) if pass_bytes else serialization.NoEncryption()
            enc = serialization.Encoding.DER if pass_bytes else serialization.Encoding.Raw
            fmt = serialization.PrivateFormat.PKCS8 if pass_bytes else serialization.PrivateFormat.Raw
            object.__setattr__(identity, "_Identity__sign_lock", threading.Lock())
            object.__setattr__(
                identity,
                "_Identity__private_key",
                base64.b64encode(
                    private.private_bytes(
                        encoding=enc,
                        format=fmt,
                        encryption_algorithm=alg,
                    )
                ).decode(),
            )
            return identity
        private = ed25519.Ed25519PrivateKey.generate()
        public = private.public_key()
        identity = cls(
            service_id=service_id,
            public_key=base64.b64encode(
                public.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode(),
            encrypted=encryption_passphrase is not None,
            created_at=now,
        )
        pass_bytes = encryption_passphrase.encode() if encryption_passphrase else None
        alg = serialization.BestAvailableEncryption(pass_bytes) if pass_bytes else serialization.NoEncryption()
        enc = serialization.Encoding.DER if pass_bytes else serialization.Encoding.Raw
        fmt = serialization.PrivateFormat.PKCS8 if pass_bytes else serialization.PrivateFormat.Raw
        object.__setattr__(
            identity,
            "_Identity__private_key",
            base64.b64encode(
                private.private_bytes(
                    encoding=enc,
                    format=fmt,
                    encryption_algorithm=alg,
                )
            ).decode(),
        )
        if secrets_manager is not None:
            identity.persist(secrets_manager)
        return identity

    def to_pem(self, passphrase: str | None = None) -> str:
        """Returns the private key as a PEM-encoded string.

        The result is suitable for storage in a secrets backend and for
        re-loading via ``Identity.create(private_key_pem=...)``.
        """
        with self.__sign_lock:
            pk = self.__private_key
        if pk is None:
            raise IdentityError("private key not loaded")
        raw = base64.b64decode(pk)
        if self.encrypted:
            loaded = serialization.load_der_private_key(raw, password=passphrase.encode() if passphrase else b"")
        else:
            loaded = ed25519.Ed25519PrivateKey.from_private_bytes(raw)
        if not isinstance(loaded, ed25519.Ed25519PrivateKey):
            raise IdentityError("not an Ed25519 private key")
        return loaded.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

    def persist(self, secrets_manager: PrivateKeyBackend) -> None:
        """Stores this identity's private key in the secrets backend.

        No-op if a private key is not loaded. Use after generating a new
        identity so the key survives process restarts.
        """
        if secrets_manager is None:
            return
        with self.__sign_lock:
            pk = self.__private_key
        if pk is None:
            raise IdentityError("private key not loaded")
        secrets_manager.store_private_key(self.service_id, self.to_pem())

    def sign(self, payload: str, passphrase: str | None = None) -> str:
        """Signs a string payload and returns a base64-encoded signature.

        Args:
            payload: The string to sign.
            passphrase: Required if the private key was stored encrypted.
        """
        with self.__sign_lock:
            pk = self.__private_key
        if pk is None:
            raise IdentityError("private key not loaded")
        raw = base64.b64decode(pk)
        if self.encrypted:
            loaded = serialization.load_der_private_key(raw, password=passphrase.encode() if passphrase else b"")
            if not isinstance(loaded, ed25519.Ed25519PrivateKey):
                raise IdentityError("encrypted key is not Ed25519")
            private = loaded
        else:
            private = ed25519.Ed25519PrivateKey.from_private_bytes(raw)
        return base64.b64encode(private.sign(payload.encode("utf-8"))).decode()

    def verify(self, payload: str, signature: str) -> bool:
        """Verifies a base64-encoded signature against a payload."""
        try:
            public_bytes = base64.b64decode(self.public_key)
            public = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
            public.verify(base64.b64decode(signature), payload.encode("utf-8"))
            return True
        except InvalidSignature:
            return False
