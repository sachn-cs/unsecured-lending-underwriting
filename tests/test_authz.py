"""Tests for AccessControl."""

from __future__ import annotations

import json

from underwrite.__authz__ import AccessControl
from underwrite.__events__ import Event
from underwrite.__exceptions__ import AuthzError
from underwrite.__identity__ import Identity


class TestAccessControl:

    def test_default_deny(self) -> None:
        acl = AccessControl()
        assert acl.check_publish("risk", "loan.originated") is False

    def test_allow_publish(self) -> None:
        acl = AccessControl()
        acl.allow("risk", "publish:loan.originated")
        assert acl.check_publish("risk", "loan.originated") is True

    def test_allow_subscribe(self) -> None:
        acl = AccessControl()
        acl.allow("audit", "subscribe:*")
        assert acl.check_subscribe("audit", "loan.originated") is True

    def test_deny_overrides_allow(self) -> None:
        acl = AccessControl()
        acl.allow("*", "publish:*")
        acl.deny("risk", "publish:loan.originated")
        assert acl.check_publish("risk", "loan.originated") is False

    def test_wildcard_subject(self) -> None:
        acl = AccessControl()
        acl.allow("*", "publish:*")
        assert acl.check_publish("anyone", "anything") is True

    def test_assert_publish(self) -> None:
        acl = AccessControl()
        acl.allow("risk", "publish:risk.scored")
        acl.assert_publish("risk", "risk.scored")

    def test_assert_publish_raises(self) -> None:
        acl = AccessControl()
        try:
            acl.assert_publish("risk", "risk.scored")
            raise AssertionError("expected AuthzError")
        except AuthzError:
            pass

    def test_signature_verify_roundtrip(self) -> None:
        acl = AccessControl()
        identity = Identity.create("risk")
        acl.trust("risk", identity.public_key)
        event = Event(
            event_type="risk.scored",
            source="risk",
            source_key=identity.public_key,
            payload={},
        )
        payload_str = json.dumps(event.payload, sort_keys=True, default=str)
        to_sign = f"{event.event_id}:{event.timestamp}:{event.event_type}:{payload_str}"
        signed = Event(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            source_key=event.source_key,
            timestamp=event.timestamp,
            payload=event.payload,
            correlation_id=event.correlation_id,
            signature=identity.sign(to_sign),
        )
        assert acl.verify_signature(signed) is True

    def test_signature_verify_rejects_tampered_payload(self) -> None:
        """Signature now covers payload — tampered payload must fail."""
        acl = AccessControl()
        identity = Identity.create("risk")
        acl.trust("risk", identity.public_key)
        event = Event(
            event_type="risk.scored",
            source="risk",
            source_key=identity.public_key,
            payload={},
        )
        to_sign = f"{event.event_id}:{event.timestamp}:{event.event_type}:{{}}"
        signed = Event(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            source_key=event.source_key,
            timestamp=event.timestamp,
            payload=event.payload,
            correlation_id=event.correlation_id,
            signature=identity.sign(to_sign),
        )
        tampered = Event(
            event_id=signed.event_id,
            event_type=signed.event_type,
            source=signed.source,
            source_key=signed.source_key,
            timestamp=signed.timestamp,
            payload={"hacked": True},
            correlation_id=signed.correlation_id,
            signature=signed.signature,
        )
        assert acl.verify_signature(tampered) is False

    def test_assert_verified(self) -> None:
        acl = AccessControl()
        identity = Identity.create("risk")
        acl.trust("risk", identity.public_key)
        event = Event(
            event_type="risk.scored",
            source="risk",
            source_key=identity.public_key,
        )
        payload_str = json.dumps(event.payload, sort_keys=True, default=str)
        to_sign = f"{event.event_id}:{event.timestamp}:{event.event_type}:{payload_str}"
        signed = Event(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            source_key=event.source_key,
            timestamp=event.timestamp,
            payload=event.payload,
            correlation_id=event.correlation_id,
            signature=identity.sign(to_sign),
        )
        acl.assert_verified(signed)

    def test_verify_without_trusted_key(self) -> None:
        acl = AccessControl()
        event = Event(event_type="t", source="unknown")
        assert acl.verify_signature(event) is False
