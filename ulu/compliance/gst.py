"""GST return verification for business borrowers.

Item 15 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ulu.infra.logging import logger


@dataclass
class GstReturn:
    """Represents a single GST return filing."""

    gstin: str
    return_period: str
    filing_date: str
    turnover: float
    tax_paid: float
    status: str  # "filed", "pending", "late"


class GstVerificationService:
    """Verifies GST filing history as a creditworthiness signal.

    Production implementation should integrate with GSTN APIs
    after obtaining API credentials from GST Network.
    """

    def __init__(self, base_url: str = "https://api.gst.gov.in") -> None:
        self.base_url = base_url

    def verify_gstin(self, gstin: str) -> dict[str, Any]:
        """Stub: validates GSTIN format and returns placeholder data."""
        if not self._is_valid_format(gstin):
            return {"valid": False, "error": "invalid GSTIN format"}
        logger.info("gst_verification_stub", gstin=gstin[:6] + "****")
        return {
            "valid": True,
            "gstin": gstin,
            "legal_name": "",
            "status": "active",
            "note": "stub: production requires GSTN API integration",
        }

    def fetch_returns(
        self,
        gstin: str,
        financial_year: str,
    ) -> list[GstReturn]:
        """Stub: returns placeholder return history."""
        logger.info("gst_returns_stub", gstin=gstin[:6] + "****", fy=financial_year)
        return []

    @staticmethod
    def _is_valid_format(gstin: str) -> bool:
        """Basic GSTIN format check (15 characters: 2 state + 10 PAN + 1 entity + Z + checksum)."""
        if len(gstin) != 15:
            return False
        return (
            gstin[:2].isdigit()
            and gstin[2:12].isalnum()
            and gstin[12].isdigit()
            and gstin[13].upper() == "Z"
            and gstin[14].isalnum()
        )

    def filing_consistency_score(self, returns: list[GstReturn]) -> float:
        """Returns a score between 0.0 and 1.0 based on filing consistency."""
        if not returns:
            return 0.0
        filed = sum(1 for r in returns if r.status == "filed")
        late = sum(1 for r in returns if r.status == "late")
        return max(0.0, (filed - late * 0.5) / len(returns))
