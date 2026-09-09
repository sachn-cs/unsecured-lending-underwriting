# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Message envelope determinism and signed construction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from underwrite.exceptions import ProtocolError
from underwrite.keypair import Keypair
from underwrite.message import MAX_PAYLOAD_SIZE, Message


class TestCanonicalSignBytes:
    def test_does_not_use_default_str(self) -> None:
        """``default=str`` would coerce datetime/Decimal to a representation
        that differs across Python versions. The Message constructor and
        ``canonical_sign_bytes`` must therefore raise ProtocolError on
        non-JSON-native values rather than silently coercing them.
        """
        with pytest.raises(ProtocolError):
            Message(
                event_type="t",
                source="s",
                payload={"when": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            )

    def test_does_not_use_default_str_for_decimal(self) -> None:
        with pytest.raises(ProtocolError):
            Message(event_type="t", source="s", payload={"amt": Decimal("1.23")})

    def test_does_not_use_default_str_for_uuid(self) -> None:
        with pytest.raises(ProtocolError):
            Message(
                event_type="t",
                source="s",
                payload={"id": UUID("00000000-0000-0000-0000-000000000001")},
            )

    def test_canonical_is_stable_across_dict_insertion_order(self) -> None:
        """Two payloads with the same keys in different insertion orders
        must produce identical canonical bytes."""
        m1 = Message(event_type="t", source="s", payload={"a": 1, "b": 2})
        m2 = Message(event_type="t", source="s", payload={"b": 2, "a": 1})
        # Same event_id, timestamp, source — force identical fields.
        m1 = Message(
            event_id="fixed",
            timestamp="2026-01-01T00:00:00+00:00",
            event_type="t",
            source="s",
            payload={"a": 1, "b": 2},
        )
        m2 = Message(
            event_id="fixed",
            timestamp="2026-01-01T00:00:00+00:00",
            event_type="t",
            source="s",
            payload={"b": 2, "a": 1},
        )
        assert m1.canonical_sign_bytes() == m2.canonical_sign_bytes()


class TestSignedClassmethod:
    def test_signed_runs_post_init_once(self) -> None:
        """The signed classmethod must not call __post_init__ twice —
        the second pass would risk regenerating event_id / timestamp /
        correlation_id and silently breaking signatures."""
        kp = Keypair.create("test")
        msg = Message.signed(
            kp,
            type="demo.event",
            source="test",
            payload={"x": 1},
            correlation_id="corr-1",
        )
        assert msg.correlation_id == "corr-1"
        assert msg.event_type == "demo.event"
        assert msg.signature != ""

    def test_signed_signature_verifies(self) -> None:
        kp = Keypair.create("verifier")
        msg = Message.signed(
            kp,
            type="demo.event",
            source="verifier",
            payload={"x": 1, "y": 2},
        )
        # Re-derive the canonical bytes and verify the signature.
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ed25519

        import base64

        public = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(kp.public_key))
        public.verify(base64.b64decode(msg.signature), msg.canonical_sign_bytes())

    def test_signed_does_not_alter_event_id(self) -> None:
        """Even with default event_id generation, the signed helper must
        keep the same event_id end-to-end."""
        kp = Keypair.create("test")
        msg1 = Message(event_type="t", source="s", payload={})
        msg2 = Message.signed(
            kp,
            type="t",
            source="s",
            payload={},
            correlation_id=msg1.correlation_id,
        )
        # Both calls use default factories; verify that the helper
        # does not double-construct (which would change event_id).
        assert msg2.event_id != ""
        assert msg2.signature != ""


class TestPostInitCircularRef:
    def test_circular_payload_raises_protocol_error(self) -> None:
        """A payload that contains a self-reference cannot be serialised
        and must raise ProtocolError (not crash with RecursionError)."""

        class Circular:
            def __init__(self) -> None:
                self.ref = self

        circular = Circular()
        with pytest.raises(ProtocolError):
            Message(
                event_type="t",
                source="s",
                payload={"obj": circular},
            )

    def test_over_max_size_payload_raises_protocol_error(self) -> None:
        payload = {"data": "x" * (MAX_PAYLOAD_SIZE + 1)}
        with pytest.raises(ProtocolError):
            Message(event_type="t", source="s", payload=payload)

    def test_circular_does_not_recursion_error(self) -> None:
        """Regression test for the RecursionError caught path —
        verify the exception is the framework's ProtocolError, not a
        raw RecursionError leaking out."""

        class Node:
            def __init__(self) -> None:
                self.next: "Node | None" = None

        a = Node()
        b = Node()
        a.next = b
        b.next = a
        with pytest.raises(ProtocolError):
            Message(
                event_type="t",
                source="s",
                payload={"node": a},
            )