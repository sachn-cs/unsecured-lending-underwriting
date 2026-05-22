"""Exhaustive tests for OriginationService."""
from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__store__ import MemoryStore
from underwrite.services.origination.service import OriginationService


class TestOriginationService:

    def test_creates_application_with_valid_data(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 50000
                  }))
        keys = svc.store.keys("origination:app_alice_")
        assert len(keys) == 1
        rec = svc.store.get(keys[0])
        assert rec["borrower"] == "alice"
        assert rec["principal"] == 50000
        assert rec["status"] == "created"

    def test_emits_origination_created_on_create(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.ORIGINATION_CREATED,
                      lambda e: received.append(e))
        svc = OriginationService(service_id="origination", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "bob",
                      "principal": 30000
                  }))
        assert len(received) == 1
        assert received[0].payload["borrower"] == "bob"
        assert received[0].payload["principal"] == 30000

    def test_rejects_empty_borrower(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "",
                      "principal": 50000
                  }))
        assert len(svc.store.keys("origination:")) == 0

    def test_rejects_zero_principal(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 0
                  }))
        assert len(svc.store.keys("origination:")) == 0

    def test_submit_transitions_to_submitted(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "carol",
                      "principal": 10000
                  }))
        app_id = svc.store.keys("origination:app_carol_")[0].replace(
            "origination:", "")
        svc.handle(
            Event(event_type="origination.submit",
                  source="test",
                  payload={"application_id": app_id}))
        rec = svc.store.get(f"origination:{app_id}")
        assert rec["status"] == "submitted"
        assert "submitted_at" in rec

    def test_submit_unknown_application_noop(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.submit",
                  source="test",
                  payload={"application_id": "nonexistent"}))
        assert len(svc.store.keys("origination:")) == 0

    def test_submit_already_submitted_noop(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "dave",
                      "principal": 1000
                  }))
        app_id = svc.store.keys("origination:app_dave_")[0].replace(
            "origination:", "")
        svc.handle(
            Event(event_type="origination.submit",
                  source="test",
                  payload={"application_id": app_id}))
        svc.handle(
            Event(event_type="origination.submit",
                  source="test",
                  payload={"application_id": app_id}))
        rec = svc.store.get(f"origination:{app_id}")
        assert rec["status"] == "submitted"

    def test_submit_emits_origination_submitted(self) -> None:
        bus = LocalBus()
        store = MemoryStore()
        received: list = []
        bus.subscribe(EventType.ORIGINATION_SUBMITTED,
                      lambda e: received.append(e))
        svc = OriginationService(service_id="origination", bus=bus, store=store)
        store.set("origination:app_1", {
            "borrower": "eve",
            "principal": 5000,
            "status": "created"
        })
        bus.start()
        svc.handle(
            Event(event_type="origination.submit",
                  source="test",
                  payload={"application_id": "app_1"}))
        assert len(received) == 1
        assert received[0].payload["application_id"] == "app_1"

    def test_ignores_unrelated_events(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("origination:")) == 0

    def test_multiple_applications_independent(self) -> None:
        svc = OriginationService(service_id="origination")
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "a",
                      "principal": 100
                  }))
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "b",
                      "principal": 200
                  }))
        assert len(svc.store.keys("origination:app_a_")) == 1
        assert len(svc.store.keys("origination:app_b_")) == 1

    def test_correlation_id_preserved(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe("*", lambda e: received.append(e))
        svc = OriginationService(service_id="origination", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="origination.create",
                  source="test",
                  payload={
                      "borrower": "f",
                      "principal": 100
                  },
                  correlation_id="corr-1"))
        emitted = [e for e in received if e.source == "origination"]
        assert len(emitted) == 1
        assert emitted[0].correlation_id == "corr-1"

    def test_health_check(self) -> None:
        svc = OriginationService(service_id="origination")
        h = svc.health_check()
        assert h["ok"] is False
        svc.start()
        h = svc.health_check()
        assert h["ok"] is True
