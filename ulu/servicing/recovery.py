"""Recovery workflows for defaulted loans."""

from __future__ import annotations

from typing import Any

from ulu.audit import AppendOnlyLedger
from ulu.domain.events import DefaultEvent, RecoveryEvent
from ulu.domain.loans import RecoveryType
from ulu.infra.logging import logger


class RecoveryService:
    """Manages workout, restructuring, liquidation, and write-off workflows."""

    def __init__(self, ledger: AppendOnlyLedger | None = None) -> None:
        self.ledger = ledger

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.ledger is not None:
            self.ledger.append(event_type=event_type, payload=payload)
            logger.info("recovery_event_appended", event_type=event_type, loan_id=payload.get("loan_id"))

    def initiate_recovery(
        self,
        loan_id: str,
        borrower_id: str,
        default_amount: float,
        recovery_type: RecoveryType,
        collateral_value: float = 0.0,
    ) -> tuple[float, DefaultEvent, RecoveryEvent]:
        """Initiates a recovery workflow and returns recovered amount plus event."""
        if recovery_type == RecoveryType.LIQUIDATION:
            recovered = collateral_value
        elif recovery_type == RecoveryType.WRITE_OFF:
            recovered = 0.0
        elif recovery_type == RecoveryType.WORKOUT:
            recovered = default_amount * 0.5
        elif recovery_type == RecoveryType.RESTRUCTURE:
            recovered = default_amount * 0.5
        else:
            raise ValueError(f"unrecognized recovery type: {recovery_type}")

        default_event = DefaultEvent(
            event_type="default",
            payload={
                "loan_id": loan_id,
                "borrower_id": borrower_id,
                "default_amount": default_amount,
                "recovery_type": recovery_type.value,
                "recovered_amount": recovered,
            },
            loan_id=loan_id,
            borrower_id=borrower_id,
            default_amount=default_amount,
            logical_loss=default_amount,
            physical_recovery=recovered,
        )
        recovery_event = RecoveryEvent(
            event_type="recovery",
            payload={
                "loan_id": loan_id,
                "borrower_id": borrower_id,
                "recovery_type": recovery_type.value,
                "recovered_amount": recovered,
                "default_amount": default_amount,
            },
            loan_id=loan_id,
            borrower_id=borrower_id,
            recovery_type=recovery_type.value,
            recovered_amount=recovered,
            default_amount=default_amount,
        )
        self._append_event("recovery_initiated", recovery_event.payload)
        self._append_event("default", default_event.payload)
        return recovered, default_event, recovery_event
