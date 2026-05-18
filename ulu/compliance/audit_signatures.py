"""Regulatory audit trail immutability via HSM or key-based signatures.

Item 18 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import hmac

from ulu.infra.logging import logger
from ulu.infra.secrets import EnvSecretManager


@dataclasses.dataclass
class SignedAuditEvent:
    """An audit event with a cryptographic signature proving integrity."""

    event_id: str
    event_type: str
    payload_hash: str
    signature: str
    algorithm: str
    signed_at: datetime.datetime


class AuditSignatureService:
    """Signs audit events with HMAC-SHA256 to guarantee immutability.

    Production should integrate with an HSM (e.g., AWS CloudHSM, Thales Luna)
    or HashiCorp Vault Transit engine instead of a raw env secret.
    """

    def __init__(self, secret_key: str | None = None) -> None:
        if secret_key is None:
            secret_key = EnvSecretManager().get("AUDIT_SIGNING_KEY") or "dev-audit-key-do-not-use"
        self._secret = secret_key.encode("utf-8")

    def _hash_payload(self, event_type: str, payload: dict[str, object]) -> str:
        canonical = f"{event_type}:{sorted(payload.items())}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def sign(self, event_id: str, event_type: str, payload: dict[str, object]) -> SignedAuditEvent:
        payload_hash = self._hash_payload(event_type, payload)
        message = f"{event_id}:{event_type}:{payload_hash}".encode()
        signature = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        signed = SignedAuditEvent(
            event_id=event_id,
            event_type=event_type,
            payload_hash=payload_hash,
            signature=signature,
            algorithm="HMAC-SHA256",
            signed_at=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        logger.info("audit_event_signed", event_id=event_id, algorithm=signed.algorithm)
        return signed

    def verify(self, signed_event: SignedAuditEvent, payload: dict[str, object]) -> bool:
        expected_hash = self._hash_payload(signed_event.event_type, payload)
        if expected_hash != signed_event.payload_hash:
            return False
        message = f"{signed_event.event_id}:{signed_event.event_type}:{signed_event.payload_hash}".encode()
        expected_sig = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, signed_event.signature)
