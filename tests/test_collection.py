"""Tests for CollectionService — repayment schedule tracking."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.collection.service import CollectionService


def svc(bus=None) -> CollectionService:
    return CollectionService(service_id="collection", bus=bus)


class TestCollectionService:

    def test_tracks_loan_on_origination(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.COLLECTION_UPDATED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 12000,
                      "term": 12
                  }))
        assert len(received) == 1
        assert received[0].payload["monthly"] == 1000.0
        assert received[0].payload["status"] == "active"

    def test_updates_on_repayment(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.COLLECTION_UPDATED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "bob",
                      "principal": 6000,
                      "term": 6
                  }))
        received.clear()
        svc_inst.handle(
            Event(event_type=EventType.REPAID,
                  source="test",
                  payload={
                      "user": "bob",
                      "delta_earned": 1000
                  }))
        assert len(received) == 1
        assert received[0].payload["paid"] == 1000.0

    def test_closes_loan_when_fully_repaid(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "carol",
                      "principal": 5000,
                      "term": 1
                  }))
        svc_inst.handle(
            Event(event_type=EventType.REPAID,
                  source="test",
                  payload={
                      "user": "carol",
                      "delta_earned": 5000
                  }))
        loan = svc_inst.get("carol")
        assert loan["status"] == "closed"

    def test_unknown_borrower_returns_none(self) -> None:
        assert svc().get("ghost") is None

    def test_repay_unknown_user_no_crash(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Event(event_type=EventType.REPAID,
                  source="test",
                  payload={
                      "user": "ghost",
                      "delta_earned": 100
                  }))

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.COLLECTION_UPDATED,
                      lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0
