"""Recovery workflows for defaulted loans."""

from __future__ import annotations

from ulu.domain.events import DefaultEvent
from ulu.domain.loans import RecoveryType


class RecoveryService:
    """Manages workout, restructuring, liquidation, and write-off workflows."""

    def initiate_recovery(
        self,
        loan_id: str,
        borrower_id: str,
        default_amount: float,
        recovery_type: RecoveryType,
        collateral_value: float = 0.0,
    ) -> tuple[float, DefaultEvent]:
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

        event = DefaultEvent(
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
        return recovered, event
