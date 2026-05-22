"""Exhaustive tests for StatementService."""
from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__store__ import MemoryStore
from underwrite.services.statement.service import StatementService


class TestStatementService:

    def test_generates_statement(self) -> None:
        store = MemoryStore()
        store.set("loan:L1", {"outstanding": 50000})
        svc = StatementService(service_id="statement", store=store)
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "period_start": "2025-01-01"
                  }))
        keys = store.keys("statement:stmt_L1_2025-01-01")
        assert len(keys) == 1
        rec = store.get(keys[0])
        assert rec["outstanding"] == 50000
        assert rec["loan_id"] == "L1"

    def test_generate_emits_statement_generated(self) -> None:
        bus = LocalBus()
        store = MemoryStore()
        store.set("loan:L2", {"outstanding": 30000})
        received: list = []
        bus.subscribe(EventType.STATEMENT_GENERATED,
                      lambda e: received.append(e))
        svc = StatementService(service_id="statement", bus=bus, store=store)
        bus.start()
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={
                      "loan_id": "L2",
                      "period_start": "2025-02-01"
                  }))
        assert len(received) == 1
        assert received[0].payload["outstanding"] == 30000

    def test_rejects_missing_loan_id(self) -> None:
        svc = StatementService(service_id="statement")
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={"period_start": "2025-01-01"}))
        assert len(svc.store.keys("statement:")) == 0

    def test_rejects_missing_period_start(self) -> None:
        svc = StatementService(service_id="statement")
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={"loan_id": "L3"}))
        assert len(svc.store.keys("statement:")) == 0

    def test_deduplicates_by_statement_id(self) -> None:
        store = MemoryStore()
        store.set("loan:L4", {"outstanding": 10000})
        svc = StatementService(service_id="statement", store=store)
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={
                      "loan_id": "L4",
                      "period_start": "2025-03-01"
                  }))
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={
                      "loan_id": "L4",
                      "period_start": "2025-03-01"
                  }))
        assert len(store.keys("statement:stmt_L4_2025-03-01")) == 1

    def test_includes_total_paid(self) -> None:
        store = MemoryStore()
        store.set("loan:L5", {"outstanding": 20000})
        store.set("payment:L5:1", {"loan_id": "L5", "amount": 1000})
        store.set("payment:L5:2", {"loan_id": "L5", "amount": 500})
        svc = StatementService(service_id="statement", store=store)
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={
                      "loan_id": "L5",
                      "period_start": "2025-04-01"
                  }))
        key = store.keys("statement:stmt_L5_2025-04-01")[0]
        rec = store.get(key)
        assert rec["total_paid"] == 1500
        assert rec["transaction_count"] == 2

    def test_tracks_collection_update(self) -> None:
        svc = StatementService(service_id="statement")
        svc.handle(
            Event(event_type=EventType.COLLECTION_UPDATED,
                  source="test",
                  payload={"loan_id": "L6"}))
        keys = svc.store.keys("stmt_trigger:L6:")
        assert len(keys) == 1

    def test_tracks_payment_received(self) -> None:
        svc = StatementService(service_id="statement")
        svc.handle(
            Event(event_type=EventType.PAYMENT_RECEIVED,
                  source="test",
                  payload={"loan_id": "L7"}))
        keys = svc.store.keys("stmt_trigger:L7:")
        assert len(keys) == 1

    def test_ignores_unrelated_events(self) -> None:
        svc = StatementService(service_id="statement")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("statement:")) == 0

    def test_period_end_defaults_to_now(self) -> None:
        store = MemoryStore()
        store.set("loan:L8", {"outstanding": 0})
        svc = StatementService(service_id="statement", store=store)
        svc.handle(
            Event(event_type="statement.generate",
                  source="test",
                  payload={
                      "loan_id": "L8",
                      "period_start": "2025-05-01"
                  }))
        key = store.keys("statement:stmt_L8_2025-05-01")[0]
        rec = store.get(key)
        assert "period_end" in rec
