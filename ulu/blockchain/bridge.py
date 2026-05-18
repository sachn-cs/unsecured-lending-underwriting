"""Cross-chain bridge support for loan token interoperability.

Item 50 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum

from ulu.infra.logging import logger


class BridgeDirection(enum.Enum):
    ALGORAND_TO_ETHEREUM = "algo_to_eth"
    ETHEREUM_TO_ALGORAND = "eth_to_algo"


@dataclasses.dataclass
class BridgeTransfer:
    """Records a single cross-chain token transfer."""

    transfer_id: str
    loan_token_id: str
    amount: float
    direction: BridgeDirection
    source_address: str
    destination_address: str
    status: str  # pending, confirmed, completed, failed
    created_at: datetime.datetime
    completed_at: datetime.datetime | None = None


class CrossChainBridge:
    """Stub cross-chain bridge for locking and minting loan tokens across chains.

    Production should integrate with Wormhole, Axelar, or LayerZero.
    """

    def __init__(self) -> None:
        self._transfers: dict[str, BridgeTransfer] = {}

    def lock_and_mint(
        self,
        transfer_id: str,
        loan_token_id: str,
        amount: float,
        direction: BridgeDirection,
        source_address: str,
        destination_address: str,
    ) -> BridgeTransfer:
        if transfer_id in self._transfers:
            raise ValueError(f"transfer already exists: {transfer_id}")
        transfer = BridgeTransfer(
            transfer_id=transfer_id,
            loan_token_id=loan_token_id,
            amount=amount,
            direction=direction,
            source_address=source_address,
            destination_address=destination_address,
            status="pending",
            created_at=datetime.datetime.now(tz=datetime.timezone.utc),
        )
        self._transfers[transfer_id] = transfer
        logger.info(
            "bridge_lock_and_mint",
            transfer_id=transfer_id,
            direction=direction.value,
            amount=amount,
        )
        return transfer

    def confirm(self, transfer_id: str) -> BridgeTransfer:
        transfer = self._get(transfer_id)
        if transfer.status != "pending":
            raise ValueError("only pending transfers can be confirmed")
        transfer.status = "confirmed"
        logger.info("bridge_confirmed", transfer_id=transfer_id)
        return transfer

    def complete(self, transfer_id: str) -> BridgeTransfer:
        transfer = self._get(transfer_id)
        if transfer.status != "confirmed":
            raise ValueError("only confirmed transfers can be completed")
        transfer.status = "completed"
        transfer.completed_at = datetime.datetime.now(tz=datetime.timezone.utc)
        logger.info("bridge_completed", transfer_id=transfer_id)
        return transfer

    def fail(self, transfer_id: str, reason: str) -> BridgeTransfer:
        transfer = self._get(transfer_id)
        transfer.status = "failed"
        logger.info("bridge_failed", transfer_id=transfer_id, reason=reason)
        return transfer

    def get(self, transfer_id: str) -> BridgeTransfer | None:
        return self._transfers.get(transfer_id)

    def list_by_status(self, status: str) -> list[BridgeTransfer]:
        return [t for t in self._transfers.values() if t.status == status]

    def _get(self, transfer_id: str) -> BridgeTransfer:
        transfer = self._transfers.get(transfer_id)
        if transfer is None:
            raise ValueError(f"transfer not found: {transfer_id}")
        return transfer
