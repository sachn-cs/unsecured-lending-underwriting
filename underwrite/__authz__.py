"""Access control for nano-service event bus.

Policies define which services may emit or consume which event types.
ACLs are evaluated at publish and subscribe time.
"""

from __future__ import annotations

__all__ = [
    "AccessControl",
    "HAS_CRYPTO",
    "Policy",
]

import base64
import json
import logging
import threading

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519
    HAS_CRYPTO: bool = True
except ImportError:
    HAS_CRYPTO = False

from underwrite.__events__ import Event
from underwrite.__exceptions__ import AuthzError

logger = logging.getLogger(__name__)


class Policy:
    """A single access rule: allow or deny a subject on a resource."""

    def __init__(self, effect: str, subject: str, resource: str) -> None:
        """Initialises a policy rule.

        Args:
            effect: ``"allow"`` or ``"deny"``.
            subject: Service or wildcard (``"*"``) this rule applies to.
            resource: Event-type or wildcard (``"*"``) this rule applies to.

        Raises:
            ValueError: If *effect* is not ``"allow"`` or ``"deny"``.
        """
        if effect not in ("allow", "deny"):
            raise ValueError("effect must be 'allow' or 'deny'")
        self.effect = effect
        self.subject = subject
        self.resource = resource

    def matches(self, subject: str, resource: str) -> bool:
        """Checks whether this rule applies to a given subject and resource.

        Args:
            subject: Service identifier to match.
            resource: Event-type resource to match.

        Returns:
            True if the rule matches, False otherwise.
        """
        if self.subject == "*" or self.subject == subject:
            if self.resource == "*":
                return True
            if self.resource.endswith("*"):
                return resource.startswith(self.resource[:-1])
            if self.resource == resource:
                return True
        return False


class AccessControl:
    """Thread-safe access control evaluator.

    Policies are evaluated in order.  The first matching rule decides.
    If no rule matches, the default is deny.
    """

    def __init__(self) -> None:
        """Initialises an empty access-control evaluator."""
        self.__lock: threading.Lock = threading.Lock()
        self.__policies: list[Policy] = []
        self.__trusted_keys: dict[str, str] = {}  # service_id -> public_key

    def allow(self, subject: str, resource: str) -> None:
        """Grants a subject permission to access a resource.

        Args:
            subject: Service identifier or ``"*"`` (all).
            resource: Event-type or ``"*"`` (all).
        """
        with self.__lock:
            self.__policies.append(Policy("allow", subject, resource))

    def deny(self, subject: str, resource: str) -> None:
        """Denies a subject access to a resource.

        Args:
            subject: Service identifier or ``"*"`` (all).
            resource: Event-type or ``"*"`` (all).
        """
        with self.__lock:
            self.__policies.append(Policy("deny", subject, resource))

    def trust(self, service_id: str, public_key: str) -> None:
        """Registers a trusted public key for a service.

        Args:
            service_id: Service identifier.
            public_key: Base64-encoded Ed25519 public key.
        """
        with self.__lock:
            self.__trusted_keys[service_id] = public_key

    def revoke_trust(self, service_id: str) -> None:
        """Removes a previously registered trusted key.

        Args:
            service_id: Service identifier whose trust to revoke.
        """
        with self.__lock:
            self.__trusted_keys.pop(service_id, None)

    def check_publish(self, subject: str, event_type: str) -> bool:
        """Checks whether a subject may publish an event type.

        Args:
            subject: Service identifier.
            event_type: Event type to check.

        Returns:
            True if allowed, False if denied.
        """
        return self.__check(subject, f"publish:{event_type}")

    def check_subscribe(self, subject: str, event_type: str) -> bool:
        """Checks whether a subject may subscribe to an event type.

        Args:
            subject: Service identifier.
            event_type: Event type to check.

        Returns:
            True if allowed, False if denied.
        """
        return self.__check(subject, f"subscribe:{event_type}")

    def __check(self, subject: str, resource: str) -> bool:
        with self.__lock:
            for p in self.__policies:
                if p.effect == "deny" and p.matches(subject, resource):
                    return False
            for p in self.__policies:
                if p.effect == "allow" and p.matches(subject, resource):
                    return True
        return False

    def verify_signature(self, event: Event) -> bool:
        """Verifies an event's Ed25519 signature against the issuer's trusted key.

        When the ``cryptography`` library is not installed, all
        signatures are accepted (insecure — for development only).
        """
        if not HAS_CRYPTO:
            return True  # dev mode: trust everything
        with self.__lock:
            public_key_b64 = self.__trusted_keys.get(event.source)
        if not public_key_b64:
            return False
        try:
            public_bytes = base64.b64decode(public_key_b64)
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(
                public_bytes)
            payload_str = json.dumps(event.payload, sort_keys=True, default=str)
            to_verify = f"{event.event_id}:{event.timestamp}:{event.event_type}:{payload_str}".encode(
            )
            signature = base64.b64decode(event.signature)
            public_key.verify(signature, to_verify)
            return True
        except InvalidSignature:
            return False
        except Exception as exc:
            logger.exception(
                "unexpected error verifying signature on event %s: %s",
                event.event_id, exc)
            return False

    def assert_publish(self, subject: str, event_type: str) -> None:
        """Asserts a subject is allowed to publish an event type.

        Args:
            subject: Service identifier.
            event_type: Event type to check.

        Raises:
            AuthzError: If the subject is not allowed to publish.
        """
        if not self.check_publish(subject, event_type):
            raise AuthzError(f"{subject} not allowed to publish {event_type}")

    def assert_subscribe(self, subject: str, event_type: str) -> None:
        """Asserts a subject is allowed to subscribe to an event type.

        Args:
            subject: Service identifier.
            event_type: Event type to check.

        Raises:
            AuthzError: If the subject is not allowed to subscribe.
        """
        if not self.check_subscribe(subject, event_type):
            raise AuthzError(
                f"{subject} not allowed to subscribe to {event_type}")

    def assert_verified(self, event: Event) -> None:
        """Asserts an event carries a valid signature from its source.

        Args:
            event: The event to verify.

        Raises:
            AuthzError: If the signature is present but invalid.
        """
        if event.signature and not self.verify_signature(event):
            raise AuthzError(
                f"invalid signature on event {event.event_id} from {event.source}"
            )
