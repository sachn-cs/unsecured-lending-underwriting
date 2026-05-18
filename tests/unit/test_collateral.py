"""Unit tests for collateral modules."""

from __future__ import annotations

import pytest

from ulu.collateral.escrow import CollateralEscrowService
from ulu.collateral.ratios import CollateralizationRatioEngine
from ulu.domain.collateral import CollateralType, LienStatus


class TestCollateralEscrowService:
    def test_create_escrow(self) -> None:
        svc = CollateralEscrowService()
        escrow = svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0, 0.1)
        assert escrow.effective_value == 9000.0
        assert escrow.lien_status == LienStatus.FREE

    def test_create_escrow_invalid_haircut(self) -> None:
        svc = CollateralEscrowService()
        with pytest.raises(ValueError):
            svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0, 1.5)

    def test_apply_lien(self) -> None:
        svc = CollateralEscrowService()
        escrow = svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        svc.apply_lien(escrow)
        assert escrow.lien_status == LienStatus.LIENED

    def test_double_lien_raises(self) -> None:
        svc = CollateralEscrowService()
        escrow = svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0)
        svc.apply_lien(escrow)
        with pytest.raises(ValueError):
            svc.apply_lien(escrow)

    def test_liquidate(self) -> None:
        svc = CollateralEscrowService()
        escrow = svc.create_escrow("u1", CollateralType.CASH_DEPOSIT, 10000.0, 0.2)
        svc.apply_lien(escrow)
        recovered = svc.liquidate(escrow)
        assert recovered == 8000.0
        assert escrow.lien_status == LienStatus.LIQUIDATED


class TestCollateralizationRatioEngine:
    def test_compute_ratio(self) -> None:
        engine = CollateralizationRatioEngine(min_ratio=0.05)
        assert engine.compute_ratio(500.0, 10000.0) == 0.05

    def test_check_breach(self) -> None:
        engine = CollateralizationRatioEngine(min_ratio=0.05)
        event = engine.check_breach("u1", 400.0, 10000.0)
        assert event is not None
        assert event.current_ratio == 0.04

    def test_no_breach(self) -> None:
        engine = CollateralizationRatioEngine(min_ratio=0.05)
        event = engine.check_breach("u1", 600.0, 10000.0)
        assert event is None

    def test_zero_outstanding(self) -> None:
        engine = CollateralizationRatioEngine(min_ratio=0.05)
        assert engine.compute_ratio(0.0, 0.0) == 1.0
