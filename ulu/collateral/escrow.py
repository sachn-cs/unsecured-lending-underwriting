"""Collateral escrow creation and management."""

from __future__ import annotations

from ulu.domain.collateral import CollateralEscrow, CollateralType, LienStatus


class CollateralEscrowService:
    """Service for managing collateral escrow positions."""

    def create_escrow(
        self,
        owner_id: str,
        collateral_type: CollateralType,
        nominal_value: float,
        haircut: float = 0.0,
    ) -> CollateralEscrow:
        if nominal_value <= 0:
            raise ValueError("nominal_value must be positive")
        if not (0.0 <= haircut < 1.0):
            raise ValueError("haircut must be in [0, 1)")
        effective_value = nominal_value * (1.0 - haircut)
        if effective_value <= 0:
            raise ValueError("effective_value must be positive after haircut")
        return CollateralEscrow(owner_id, collateral_type, nominal_value, haircut)

    def apply_lien(self, escrow: CollateralEscrow) -> None:
        if escrow.lien_status != LienStatus.FREE:
            raise ValueError("collateral must be free to apply lien")
        escrow.apply_lien()

    def liquidate(self, escrow: CollateralEscrow) -> float:
        if escrow.lien_status != LienStatus.LIENED:
            raise ValueError("collateral must be liened before liquidation")
        return escrow.liquidate()
