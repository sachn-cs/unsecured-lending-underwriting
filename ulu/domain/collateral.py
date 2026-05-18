"""Collateral domain models and value objects."""

from __future__ import annotations

import enum


class CollateralType(enum.Enum):
    CASH_DEPOSIT = "cash_deposit"
    LIEN_MARKED_FD = "lien_marked_fd"
    BANK_GUARANTEE = "bank_guarantee"
    SECURITY = "security"


class LienStatus(enum.Enum):
    FREE = "free"
    LIENED = "liened"
    LIQUIDATED = "liquidated"


class CollateralEscrow:
    """Domain representation of a collateral escrow position."""

    def __init__(
        self,
        owner_id: str,
        collateral_type: CollateralType,
        nominal_value: float,
        haircut: float = 0.0,
    ) -> None:
        self.owner_id = owner_id
        self.collateral_type = collateral_type
        self.nominal_value = nominal_value
        self.haircut = haircut
        self.effective_value = nominal_value * (1.0 - haircut)
        self.lien_status = LienStatus.FREE

    def apply_lien(self) -> None:
        self.lien_status = LienStatus.LIENED

    def liquidate(self) -> float:
        self.lien_status = LienStatus.LIQUIDATED
        return self.effective_value
