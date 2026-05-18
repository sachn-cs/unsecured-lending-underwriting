"""Bankruptcy and IBC proceedings tracking for defaulters.

Item 36 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ulu.infra.logging import logger


@dataclass
class IbcProceeding:
    """Represents an IBC proceeding for a defaulter."""

    borrower_id: str
    nclt_bench: str
    case_number: str
    status: str  # "admitted", "under_resolution", "resolved", "rejected", "withdrawn"
    resolution_professional: str
    claim_amount: float
    admission_date: str
    resolution_date: str = ""


class BankruptcyTrackingService:
    """Tracks IBC proceedings and NCLT status for defaulters."""

    def __init__(self) -> None:
        self._proceedings: dict[str, IbcProceeding] = {}

    def register_proceeding(self, proceeding: IbcProceeding) -> None:
        """Registers a new IBC proceeding."""
        self._proceedings[proceeding.case_number] = proceeding
        logger.info(
            "ibc_proceeding_registered",
            borrower_id=proceeding.borrower_id,
            case_number=proceeding.case_number,
            status=proceeding.status,
        )

    def update_status(self, case_number: str, new_status: str, resolution_date: str = "") -> None:
        """Updates the status of an existing proceeding."""
        if case_number not in self._proceedings:
            raise ValueError(f"case {case_number} not found")
        self._proceedings[case_number].status = new_status
        if resolution_date:
            self._proceedings[case_number].resolution_date = resolution_date
        logger.info(
            "ibc_status_updated",
            case_number=case_number,
            new_status=new_status,
        )

    def get_proceeding(self, case_number: str) -> IbcProceeding | None:
        return self._proceedings.get(case_number)

    def get_by_borrower(self, borrower_id: str) -> list[IbcProceeding]:
        return [p for p in self._proceedings.values() if p.borrower_id == borrower_id]

    def list_active(self) -> list[IbcProceeding]:
        """Returns proceedings that are not yet resolved or rejected."""
        return [
            p
            for p in self._proceedings.values()
            if p.status in ("admitted", "under_resolution")
        ]

    def is_under_resolution(self, borrower_id: str) -> bool:
        """Returns True if the borrower has any active IBC proceeding."""
        return any(
            p.borrower_id == borrower_id and p.status in ("admitted", "under_resolution")
            for p in self._proceedings.values()
        )

    def summary(self) -> dict[str, Any]:
        """Returns aggregate statistics of IBC proceedings."""
        total = len(self._proceedings)
        active = len(self.list_active())
        resolved = sum(1 for p in self._proceedings.values() if p.status == "resolved")
        total_claims = sum(p.claim_amount for p in self._proceedings.values())
        return {
            "total_proceedings": total,
            "active": active,
            "resolved": resolved,
            "rejected": total - active - resolved,
            "total_claims": total_claims,
        }
