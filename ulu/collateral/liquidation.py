"""End-to-end collateral liquidation workflow.

Item 30 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

from ulu.collateral.escrow import CollateralEscrowService
from ulu.domain.collateral import CollateralEscrow, LienStatus
from ulu.infra.logging import logger


@dataclasses.dataclass
class LiquidationRecord:
    """Tracks a single collateral liquidation attempt."""

    record_id: str
    loan_id: str
    escrow_id: str
    notice_sent_at: datetime.datetime | None = None
    auction_held_at: datetime.datetime | None = None
    recovered_amount: float = 0.0
    deficiency_amount: float = 0.0
    status: str = "initiated"  # initiated, noticed, auctioned, distributed, closed


class LiquidationWorkflowService:
    """Manages end-to-end liquidation: notice, auction, recovery distribution, deficiency tracking."""

    def __init__(self) -> None:
        self._records: dict[str, LiquidationRecord] = {}
        self._escrow_service = CollateralEscrowService()

    def initiate(self, record_id: str, loan_id: str, escrow_id: str, default_amount: float) -> LiquidationRecord:
        if record_id in self._records:
            raise ValueError(f"liquidation already exists: {record_id}")
        record = LiquidationRecord(
            record_id=record_id,
            loan_id=loan_id,
            escrow_id=escrow_id,
            status="initiated",
        )
        self._records[record_id] = record
        logger.info("liquidation_initiated", record_id=record_id, loan_id=loan_id, default_amount=default_amount)
        return record

    def send_notice(self, record_id: str) -> LiquidationRecord:
        record = self._get(record_id)
        if record.status != "initiated":
            raise ValueError("notice can only be sent after initiation")
        record.notice_sent_at = datetime.datetime.now(tz=datetime.timezone.utc)
        record.status = "noticed"
        logger.info("liquidation_notice_sent", record_id=record_id)
        return record

    def hold_auction(
        self,
        record_id: str,
        escrow: CollateralEscrow,
        recovered_amount: float | None = None,
    ) -> LiquidationRecord:
        record = self._get(record_id)
        if record.status != "noticed":
            raise ValueError("auction can only be held after notice")
        if escrow.lien_status != LienStatus.LIENED:
            raise ValueError("escrow must be liened before auction")
        actual_recovered = recovered_amount if recovered_amount is not None else self._escrow_service.liquidate(escrow)
        record.recovered_amount = actual_recovered
        record.auction_held_at = datetime.datetime.now(tz=datetime.timezone.utc)
        record.status = "auctioned"
        logger.info("liquidation_auction_held", record_id=record_id, recovered=actual_recovered)
        return record

    def distribute_recovery(self, record_id: str, default_amount: float) -> LiquidationRecord:
        record = self._get(record_id)
        if record.status != "auctioned":
            raise ValueError("recovery can only be distributed after auction")
        record.deficiency_amount = max(0.0, default_amount - record.recovered_amount)
        record.status = "distributed"
        logger.info(
            "liquidation_recovery_distributed",
            record_id=record_id,
            recovered=record.recovered_amount,
            deficiency=record.deficiency_amount,
        )
        return record

    def close(self, record_id: str) -> LiquidationRecord:
        record = self._get(record_id)
        if record.status not in {"distributed", "auctioned"}:
            raise ValueError("can only close after distribution")
        record.status = "closed"
        logger.info("liquidation_closed", record_id=record_id)
        return record

    def get(self, record_id: str) -> LiquidationRecord | None:
        return self._records.get(record_id)

    def list_by_loan(self, loan_id: str) -> list[LiquidationRecord]:
        return [r for r in self._records.values() if r.loan_id == loan_id]

    def summary(self) -> dict[str, Any]:
        total_recovered = sum(r.recovered_amount for r in self._records.values())
        total_deficiency = sum(r.deficiency_amount for r in self._records.values())
        return {
            "total_liquidations": len(self._records),
            "total_recovered": total_recovered,
            "total_deficiency": total_deficiency,
        }

    def _get(self, record_id: str) -> LiquidationRecord:
        record = self._records.get(record_id)
        if record is None:
            raise ValueError(f"liquidation record not found: {record_id}")
        return record
