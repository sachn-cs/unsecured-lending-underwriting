"""Exhaustive tests for ServicingService."""
from __future__ import annotations

from underwrite.__events__ import Event
from underwrite.services.servicing.service import ServicingService


class TestServicingService:

    def test_creates_loan_record_on_originated(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "L1",
                      "borrower": "alice",
                      "principal": 100000
                  }))
        rec = svc.store.get("loan:L1")
        assert rec["borrower"] == "alice"
        assert rec["principal"] == 100000
        assert rec["outstanding"] == 100000
        assert rec["status"] == "active"

    def test_handles_partial_repayment(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "L2",
                      "borrower": "bob",
                      "principal": 50000
                  }))
        svc.handle(
            Event(event_type="repaid",
                  source="test",
                  payload={
                      "loan_id": "L2",
                      "amount": 10000
                  }))
        rec = svc.store.get("loan:L2")
        assert rec["outstanding"] == 40000
        assert rec["status"] == "active"

    def test_marks_paid_on_full_repayment(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "L3",
                      "borrower": "carol",
                      "principal": 30000
                  }))
        svc.handle(
            Event(event_type="repaid",
                  source="test",
                  payload={
                      "loan_id": "L3",
                      "amount": 30000
                  }))
        rec = svc.store.get("loan:L3")
        assert rec["outstanding"] == 0
        assert rec["status"] == "paid"
        assert "paid_at" in rec

    def test_prevents_negative_outstanding(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "L4",
                      "borrower": "dave",
                      "principal": 10000
                  }))
        svc.handle(
            Event(event_type="repaid",
                  source="test",
                  payload={
                      "loan_id": "L4",
                      "amount": 99999
                  }))
        rec = svc.store.get("loan:L4")
        assert rec["outstanding"] == 0

    def test_handles_default(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "L5",
                      "borrower": "eve",
                      "principal": 20000
                  }))
        svc.handle(
            Event(event_type="default.occurred",
                  source="test",
                  payload={"loan_id": "L5"}))
        rec = svc.store.get("loan:L5")
        assert rec["status"] == "defaulted"
        assert "defaulted_at" in rec

    def test_unknown_loan_repayment_noop(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="repaid",
                  source="test",
                  payload={
                      "loan_id": "NONEXISTENT",
                      "amount": 100
                  }))
        assert len(svc.store.keys("loan:")) == 0

    def test_unknown_loan_default_noop(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="default.occurred",
                  source="test",
                  payload={"loan_id": "NONEXISTENT"}))
        assert len(svc.store.keys("loan:")) == 0

    def test_empty_loan_id_noop(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated", source="test", payload={}))
        assert len(svc.store.keys("loan:")) == 0

    def test_ignores_unrelated_events(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("loan:")) == 0

    def test_multiple_loans_independent(self) -> None:
        svc = ServicingService(service_id="servicing")
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "A",
                      "borrower": "a",
                      "principal": 100
                  }))
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={
                      "loan_id": "B",
                      "borrower": "b",
                      "principal": 200
                  }))
        assert svc.store.get("loan:A")["outstanding"] == 100
        assert svc.store.get("loan:B")["outstanding"] == 200
