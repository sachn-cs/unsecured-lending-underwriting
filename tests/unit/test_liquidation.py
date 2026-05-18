"""Unit tests for collateral liquidation workflow."""

from __future__ import annotations

import pytest

from ulu.collateral.escrow import CollateralEscrowService
from ulu.collateral.liquidation import LiquidationWorkflowService
from ulu.domain.collateral import CollateralType, LienStatus


class TestLiquidationWorkflowService:
    def test_initiate(self) -> None:
        svc = LiquidationWorkflowService()
        record = svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        assert record.record_id == "LQ1"
        assert record.loan_id == "loan1"
        assert record.escrow_id == "esc1"
        assert record.status == "initiated"

    def test_initiate_duplicate_raises(self) -> None:
        svc = LiquidationWorkflowService()
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        with pytest.raises(ValueError, match="already exists"):
            svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)

    def test_send_notice(self) -> None:
        svc = LiquidationWorkflowService()
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        record = svc.send_notice("LQ1")
        assert record.status == "noticed"
        assert record.notice_sent_at is not None

    def test_send_notice_wrong_status_raises(self) -> None:
        svc = LiquidationWorkflowService()
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        with pytest.raises(ValueError, match="notice can only be sent after initiation"):
            svc.send_notice("LQ1")

    def test_hold_auction(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        record = svc.hold_auction("LQ1", escrow)
        assert record.status == "auctioned"
        assert record.recovered_amount == 10000.0
        assert record.auction_held_at is not None
        assert escrow.lien_status == LienStatus.LIQUIDATED

    def test_hold_auction_not_liened_raises(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        with pytest.raises(ValueError, match="must be liened before auction"):
            svc.hold_auction("LQ1", escrow)

    def test_hold_auction_wrong_status_raises(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        with pytest.raises(ValueError, match="auction can only be held after notice"):
            svc.hold_auction("LQ1", escrow)

    def test_distribute_recovery(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        svc.hold_auction("LQ1", escrow)
        record = svc.distribute_recovery("LQ1", default_amount=12000.0)
        assert record.status == "distributed"
        assert record.deficiency_amount == 2000.0

    def test_distribute_recovery_no_deficiency(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 15000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=10000.0)
        svc.send_notice("LQ1")
        svc.hold_auction("LQ1", escrow)
        record = svc.distribute_recovery("LQ1", default_amount=10000.0)
        assert record.deficiency_amount == 0.0

    def test_distribute_recovery_wrong_status_raises(self) -> None:
        svc = LiquidationWorkflowService()
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        with pytest.raises(ValueError, match="recovery can only be distributed after auction"):
            svc.distribute_recovery("LQ1", default_amount=5000.0)

    def test_close_after_distribution(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        svc.hold_auction("LQ1", escrow)
        svc.distribute_recovery("LQ1", default_amount=5000.0)
        record = svc.close("LQ1")
        assert record.status == "closed"

    def test_close_after_auction_without_distribution(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.send_notice("LQ1")
        svc.hold_auction("LQ1", escrow)
        record = svc.close("LQ1")
        assert record.status == "closed"

    def test_close_wrong_status_raises(self) -> None:
        svc = LiquidationWorkflowService()
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        with pytest.raises(ValueError, match="can only close after distribution"):
            svc.close("LQ1")

    def test_get_and_list_by_loan(self) -> None:
        svc = LiquidationWorkflowService()
        svc.initiate("LQ1", "loan1", "esc1", default_amount=5000.0)
        svc.initiate("LQ2", "loan1", "esc2", default_amount=3000.0)
        svc.initiate("LQ3", "loan2", "esc3", default_amount=2000.0)
        assert svc.get("LQ1") is not None
        assert svc.get("LQ99") is None
        assert len(svc.list_by_loan("loan1")) == 2
        assert len(svc.list_by_loan("loan2")) == 1

    def test_summary(self) -> None:
        svc = LiquidationWorkflowService()
        escrow_svc = CollateralEscrowService()
        escrow = escrow_svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        escrow_svc.apply_lien(escrow)
        svc.initiate("LQ1", "loan1", "esc1", default_amount=12000.0)
        svc.send_notice("LQ1")
        svc.hold_auction("LQ1", escrow)
        svc.distribute_recovery("LQ1", default_amount=12000.0)
        summary = svc.summary()
        assert summary["total_liquidations"] == 1
        assert summary["total_recovered"] == 10000.0
        assert summary["total_deficiency"] == 2000.0
