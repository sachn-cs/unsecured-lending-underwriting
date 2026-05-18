"""RBI examination-ready reporting exports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class RbiReporter:
    """Generates regulatory reports for RBI Digital Lending compliance."""

    def generate_portfolio_report(
        self,
        total_outstanding: float,
        total_earned_credit: float,
        total_defaults: float,
        dlg_pool_balance: float,
    ) -> dict[str, Any]:
        """Returns a summary portfolio report."""
        return {
            "report_type": "portfolio_summary",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_outstanding_principal": total_outstanding,
            "total_earned_credit": total_earned_credit,
            "total_defaults": total_defaults,
            "dlg_pool_balance": dlg_pool_balance,
            "dlg_utilization_ratio": (total_defaults / dlg_pool_balance if dlg_pool_balance > 0 else None),
        }

    def generate_dlg_invocation_report(self, loan_id: str, recovery_amount: float, invoked_at: str) -> dict[str, Any]:
        """Returns a DLG invocation detail record."""
        return {
            "report_type": "dlg_invocation",
            "loan_id": loan_id,
            "recovery_amount": recovery_amount,
            "invoked_at": invoked_at,
            "compliance_framework": "RBI_Digital_Lending_Directions_2023",
        }
