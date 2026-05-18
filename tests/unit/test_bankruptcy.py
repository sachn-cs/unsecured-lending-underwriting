"""Unit tests for bankruptcy/IBC tracking."""

from __future__ import annotations

import pytest

from ulu.compliance.bankruptcy import BankruptcyTrackingService, IbcProceeding


class TestBankruptcyTrackingService:
    def test_register_and_get(self) -> None:
        svc = BankruptcyTrackingService()
        p = IbcProceeding(
            borrower_id="b1",
            nclt_bench="Delhi",
            case_number="IBC-001",
            status="admitted",
            resolution_professional="RP1",
            claim_amount=500000.0,
            admission_date="2026-01-01",
        )
        svc.register_proceeding(p)
        assert svc.get_proceeding("IBC-001") == p

    def test_update_status(self) -> None:
        svc = BankruptcyTrackingService()
        p = IbcProceeding(
            borrower_id="b1",
            nclt_bench="Delhi",
            case_number="IBC-001",
            status="admitted",
            resolution_professional="RP1",
            claim_amount=500000.0,
            admission_date="2026-01-01",
        )
        svc.register_proceeding(p)
        svc.update_status("IBC-001", "under_resolution")
        assert svc.get_proceeding("IBC-001").status == "under_resolution"

    def test_update_unknown_case(self) -> None:
        svc = BankruptcyTrackingService()
        with pytest.raises(ValueError, match="not found"):
            svc.update_status("IBC-999", "resolved")

    def test_get_by_borrower(self) -> None:
        svc = BankruptcyTrackingService()
        p1 = IbcProceeding("b1", "Delhi", "IBC-001", "admitted", "RP1", 100000.0, "2026-01-01")
        p2 = IbcProceeding("b1", "Mumbai", "IBC-002", "rejected", "RP2", 200000.0, "2026-02-01")
        svc.register_proceeding(p1)
        svc.register_proceeding(p2)
        assert len(svc.get_by_borrower("b1")) == 2

    def test_list_active(self) -> None:
        svc = BankruptcyTrackingService()
        p1 = IbcProceeding("b1", "Delhi", "IBC-001", "admitted", "RP1", 100000.0, "2026-01-01")
        p2 = IbcProceeding("b2", "Mumbai", "IBC-002", "resolved", "RP2", 200000.0, "2026-02-01")
        svc.register_proceeding(p1)
        svc.register_proceeding(p2)
        active = svc.list_active()
        assert len(active) == 1
        assert active[0].case_number == "IBC-001"

    def test_is_under_resolution(self) -> None:
        svc = BankruptcyTrackingService()
        p = IbcProceeding("b1", "Delhi", "IBC-001", "admitted", "RP1", 100000.0, "2026-01-01")
        svc.register_proceeding(p)
        assert svc.is_under_resolution("b1") is True
        assert svc.is_under_resolution("b2") is False

    def test_summary(self) -> None:
        svc = BankruptcyTrackingService()
        p1 = IbcProceeding("b1", "Delhi", "IBC-001", "admitted", "RP1", 100000.0, "2026-01-01")
        p2 = IbcProceeding("b2", "Mumbai", "IBC-002", "resolved", "RP2", 200000.0, "2026-02-01")
        svc.register_proceeding(p1)
        svc.register_proceeding(p2)
        summary = svc.summary()
        assert summary["total_proceedings"] == 2
        assert summary["active"] == 1
        assert summary["resolved"] == 1
        assert summary["total_claims"] == 300000.0
