"""Repayment processing engine."""

from __future__ import annotations

from ulu.domain.events import RepaymentEvent
from ulu.domain.loans import RepaymentType


class RepaymentService:
    """Processes repayments and updates earned credit."""

    def process_repayment(
        self,
        loan_id: str,
        borrower_id: str,
        amount: float,
        outstanding_principal: float,
        accrued_interest: float,
        repayment_type: RepaymentType = RepaymentType.SCHEDULED,
    ) -> tuple[float, float, float, RepaymentEvent]:
        """Applies a repayment amount to accrued interest and principal.

        Args:
            loan_id: Unique loan identifier.
            borrower_id: Borrower identifier.
            amount: Repayment amount (must be positive).
            outstanding_principal: Current outstanding principal (must be non-negative).
            accrued_interest: Current accrued interest (must be non-negative).
            repayment_type: Type of repayment.

        Returns:
            Tuple of (interest_paid, principal_paid, excess, event).

        Raises:
            ValueError: If amount is not positive, or if inputs are negative,
                        or if overpayment exceeds total due.
        """
        if amount <= 0:
            raise ValueError("repayment amount must be positive")
        if outstanding_principal < 0 or accrued_interest < 0:
            raise ValueError("outstanding_principal and accrued_interest must be non-negative")
        total_due = accrued_interest + outstanding_principal
        if amount > total_due:
            raise ValueError(f"overpayment: amount {amount} exceeds total due {total_due}")

        interest_paid = min(amount, accrued_interest)
        remaining = amount - interest_paid
        principal_paid = min(remaining, outstanding_principal)
        excess = amount - (interest_paid + principal_paid)
        delta_earned = principal_paid

        event = RepaymentEvent(
            event_type="repayment",
            payload={
                "loan_id": loan_id,
                "borrower_id": borrower_id,
                "amount": amount,
                "interest_paid": interest_paid,
                "principal_paid": principal_paid,
                "repayment_type": repayment_type.value,
            },
            loan_id=loan_id,
            amount=amount,
            delta_earned=delta_earned,
        )
        return interest_paid, principal_paid, excess, event
