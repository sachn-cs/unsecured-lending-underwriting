"""Access control for nano-service event bus.

Policies define which services may emit or consume which event types.
ACLs are evaluated at publish and subscribe time.
"""

from __future__ import annotations

__all__ = [
    "AccessControl",
    "DEFAULT_REPLAY_WINDOW_SECONDS",
    "Policy",
]

import base64
import threading
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from underwrite.events import Event
from underwrite.exceptions import AuthzError
from underwrite.logger import logger

DEFAULT_REPLAY_WINDOW_SECONDS: float = 300.0


class Policy:
    """A single access rule: allow or deny a subject on a resource."""

    def __init__(self, effect: str, subject: str, resource: str) -> None:
        """Initializes a policy rule.

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

    Deny rules are evaluated first; if any deny rule matches, access
    is denied.  Then allow rules are evaluated; if any allow rule
    matches, access is granted.  If no rule matches, the default is
    deny.  This means deny rules always take priority over allow
    rules, regardless of insertion order.
    """

    def __init__(self) -> None:
        """Initializes an empty access-control evaluator."""
        self.__lock: threading.Lock = threading.Lock()
        self.__policies: list[Policy] = []
        self.__trusted_keys: dict[str, str] = {}  # service_id -> public_key
        self.__replay_window_seconds: float = DEFAULT_REPLAY_WINDOW_SECONDS

    def set_replay_window(self, seconds: float) -> None:
        """Sets the maximum age (in seconds) of a signed event for verification.

        Events older than this window — or dated more than this far in the
        future — are rejected. Set to ``0`` or a negative value to disable
        the window check (not recommended in production).
        """
        with self.__lock:
            self.__replay_window_seconds = max(0.0, float(seconds))

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

    def is_trusted(self, service_id: str) -> bool:
        """Returns True if *service_id* has a registered trusted key."""
        with self.__lock:
            return service_id in self.__trusted_keys

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

        The signed payload binds the event id, timestamp, event type,
        source and JSON-serialised payload, so a holder of one trusted
        key cannot re-stamp an event under a different service id or
        replay an old captured event outside the configured replay
        window.
        """
        with self.__lock:
            public_key_b64 = self.__trusted_keys.get(event.source)
            window = self.__replay_window_seconds
        if not public_key_b64:
            return False
        if window > 0 and not self.__within_window(event.timestamp, window):
            return False
        try:
            public_bytes = base64.b64decode(public_key_b64)
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
            signature = base64.b64decode(event.signature)
            public_key.verify(signature, event.canonical_sign_bytes())
            return True
        except InvalidSignature:
            return False
        except (TypeError, ValueError) as exc:
            logger.exception("unexpected error verifying signature on event {}: {}", event.event_id, exc)
            return False

    @staticmethod
    def __within_window(timestamp: str, window: float) -> bool:
        try:
            ts = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (now - ts).total_seconds()
        return -window <= delta <= window

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
            raise AuthzError(f"{subject} not allowed to subscribe to {event_type}")

    def assert_verified(self, event: Event) -> None:
        """Asserts an event carries a valid signature from its source.

        Args:
            event: The event to verify.

        Raises:
            AuthzError: If the signature is missing or invalid.
        """
        if not event.signature:
            raise AuthzError(f"missing signature on event {event.event_id} from {event.source}")
        if not self.verify_signature(event):
            raise AuthzError(f"invalid signature on event {event.event_id} from {event.source}")
