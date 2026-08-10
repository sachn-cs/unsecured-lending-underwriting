# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — key registration and rotation.

Tests verify behavior through:
  - Store state (identity:* keys)
  - Emitted IDENTITY_REGISTERED and IDENTITY_ROTATED events
"""

from __future__ import annotations

import pytest

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.identity.handler import Handler as IdentityHandler
from underwrite.store import InMemory


class TestIdentityService:
    def test_register_creates_key_in_store(self) -> None:
        store = InMemory()
        svc = IdentityHandler(name="identity", store=store, bus=LocalBus())
        svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": "risk"}))
        stored = store.get("identity:risk")
        assert stored is not None
        assert stored["name"] == "risk"
        assert len(stored["public_key"]) > 0

    def test_register_emits_registered_event(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.IDENTITY_REGISTERED, lambda e: received.append(e))
        store = InMemory()
        svc = IdentityHandler(name="identity", store=store, bus=bus or LocalBus())
        bus.start()
        svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": "fraud"}))
        assert len(received) == 1
        assert received[0].payload["name"] == "fraud"
        assert len(received[0].payload["public_key"]) > 0

    def test_rotate_updates_public_key(self) -> None:
        store = InMemory()
        svc = IdentityHandler(name="identity", store=store, bus=LocalBus())
        svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": "audit"}))
        orig_rec = store.get("identity:audit")
        assert orig_rec is not None
        original = orig_rec["public_key"]
        svc.handle(Message(event_type=Type.IDENTITY_ROTATE, source="test", payload={"name": "audit"}))
        rot_rec = store.get("identity:audit")
        assert rot_rec is not None
        rotated = rot_rec["public_key"]
        assert rotated != original

    def test_rotate_emits_rotated_event(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.IDENTITY_ROTATED, lambda e: received.append(e))
        store = InMemory()
        svc = IdentityHandler(name="identity", store=store, bus=bus or LocalBus())
        bus.start()
        svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": "gov"}))
        svc.handle(Message(event_type=Type.IDENTITY_ROTATE, source="test", payload={"name": "gov"}))
        assert len(received) == 1

    def test_multiple_registrations_independent(self) -> None:
        store = InMemory()
        svc = IdentityHandler(name="identity", store=store, bus=LocalBus())
        svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": "a"}))
        svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": "b"}))
        assert store.get("identity:a") is not None
        assert store.get("identity:b") is not None
        key_a = store.get("identity:a")
        assert key_a is not None
        key_b = store.get("identity:b")
        assert key_b is not None
        assert key_a["public_key"] != key_b["public_key"]

    def test_ignores_unrelated_events(self) -> None:
        store = InMemory()
        svc = IdentityHandler(name="identity", store=store, bus=LocalBus())
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        svc.handle(Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={}))
        assert len(store.keys()) == 0

    def test_rejects_empty_service_id(self) -> None:
        from underwrite.exceptions import ProtocolError

        svc = IdentityHandler(name="identity", store=InMemory(), bus=LocalBus())
        with pytest.raises(ProtocolError):
            svc.handle(Message(event_type=Type.IDENTITY_REGISTER, source="test", payload={"name": ""}))
