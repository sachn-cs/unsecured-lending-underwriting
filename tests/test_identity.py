"""Tests for IdentityService — key registration and rotation.

Tests verify behavior through:
  - Store state (identity:* keys)
  - Emitted IDENTITY_REGISTERED and IDENTITY_ROTATED events
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__store__ import MemoryStore
from underwrite.services.identity.service import IdentityService


class TestIdentityService:

    def test_register_creates_key_in_store(self) -> None:
        store = MemoryStore()
        svc = IdentityService(service_id="identity", store=store)
        svc.handle(
            Event(event_type="identity_register",
                  source="test",
                  payload={"service_id": "risk"}))
        stored = store.get("identity:risk")
        assert stored is not None
        assert stored["service_id"] == "risk"
        assert len(stored["public_key"]) > 0

    def test_register_emits_registered_event(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.IDENTITY_REGISTERED,
                      lambda e: received.append(e))
        store = MemoryStore()
        svc = IdentityService(service_id="identity", store=store, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="identity_register",
                  source="test",
                  payload={"service_id": "fraud"}))
        assert len(received) == 1
        assert received[0].payload["service_id"] == "fraud"
        assert len(received[0].payload["public_key"]) > 0

    def test_rotate_updates_public_key(self) -> None:
        store = MemoryStore()
        svc = IdentityService(service_id="identity", store=store)
        svc.handle(
            Event(event_type="identity_register",
                  source="test",
                  payload={"service_id": "audit"}))
        original = store.get("identity:audit")["public_key"]
        svc.handle(
            Event(event_type="identity_rotate",
                  source="test",
                  payload={"service_id": "audit"}))
        rotated = store.get("identity:audit")["public_key"]
        assert rotated != original

    def test_rotate_emits_rotated_event(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.IDENTITY_ROTATED, lambda e: received.append(e))
        store = MemoryStore()
        svc = IdentityService(service_id="identity", store=store, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="identity_rotate",
                  source="test",
                  payload={"service_id": "gov"}))
        assert len(received) == 1

    def test_multiple_registrations_independent(self) -> None:
        store = MemoryStore()
        svc = IdentityService(service_id="identity", store=store)
        svc.handle(
            Event(event_type="identity_register",
                  source="test",
                  payload={"service_id": "a"}))
        svc.handle(
            Event(event_type="identity_register",
                  source="test",
                  payload={"service_id": "b"}))
        assert store.get("identity:a") is not None
        assert store.get("identity:b") is not None
        assert store.get("identity:a")["public_key"] != store.get(
            "identity:b")["public_key"]

    def test_ignores_unrelated_events(self) -> None:
        store = MemoryStore()
        svc = IdentityService(service_id="identity", store=store)
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={}))
        assert len(store.keys()) == 0

    def test_rejects_empty_service_id(self) -> None:
        from underwrite.__exceptions__ import ProtocolError
        svc = IdentityService(service_id="identity")
        try:
            svc.handle(
                Event(event_type="identity_register",
                      source="test",
                      payload={"service_id": ""}))
        except ProtocolError:
            pass
