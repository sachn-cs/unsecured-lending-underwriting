"""RBI Digital Lending Directions compliance — DLG cap and dual-layer settlement."""

from __future__ import annotations


class RbiDlgCompliance:
    """Enforces the RBI-mandated 5% Default Loss Guarantee cap."""

    def __init__(self, dlg_cap_ratio: float) -> None:
        if not (0.0 <= dlg_cap_ratio <= 1.0):
            raise ValueError(f"dlg_cap_ratio must be in [0, 1], got {dlg_cap_ratio}")
        self.dlg_cap_ratio = dlg_cap_ratio

    def physical_recovery_limit(self, portfolio_outstanding: float) -> float:
        """Returns maximum physical cash recovery allowed under DLG."""
        return portfolio_outstanding * self.dlg_cap_ratio

    def compute_physical_recovery(self, logical_loss: float, portfolio_outstanding: float) -> float:
        """Caps logical loss to DLG limit."""
        logical_loss = max(0.0, logical_loss)
        limit = self.physical_recovery_limit(portfolio_outstanding)
        return min(logical_loss, limit)

    def remaining_bank_absorption(self, logical_loss: float, portfolio_outstanding: float) -> float:
        """Loss absorbed on bank/RE balance sheet after DLG cap."""
        physical = self.compute_physical_recovery(logical_loss, portfolio_outstanding)
        return max(0.0, logical_loss - physical)

    def can_originate(self, portfolio_outstanding: float, dlg_pool_balance: float) -> bool:
        """Returns False if DLG pool is below regulatory minimum."""
        required = portfolio_outstanding * self.dlg_cap_ratio
        return dlg_pool_balance >= required
