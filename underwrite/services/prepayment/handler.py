"""Prepayment and foreclosure service.

Handles prepayment requests and foreclosure computations per RBI
guidelines.  Foreclosure/prepayment penalty is NOT allowed on
floating-rate loans to individuals for non-business purposes.
For fixed-rate loans, a maximum 3% penalty applies.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from underwrite.amortization import (
    calculate_foreclosure,
    generate_schedule,
)
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.services.base import Core
from underwrite.validate import PayloadValidator


class PrepaymentHandler(Core):
    """Computes foreclosure quotes and processes prepayment requests."""

    def handlers(self) -> dict[str, Any]:
        """Return event type to handler mapping."""
        return {
            Type.PREPAYMENT_REQUEST: self.__on_prepayment_request,
        }

    def handle(self, event: Message) -> None:
        """Dispatch an event to the appropriate handler.

        Args:
            event: The incoming domain event.
        """
        handler = self.handlers().get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_prepayment_request(self, event: Message) -> None:
        """Compute a foreclosure quote for a prepayment request.

        Args:
            event: The PREPAYMENT_REQUEST event.
        """
        p = event.payload
        loan_id: str = p.get("loan_id", "")
        if not loan_id:
            logger.warning("PREPAYMENT_REQUEST missing loan_id, skipped")
            return
        principal: float = PayloadValidator().finite(p, "principal", 0.0)
        annual_rate: float = PayloadValidator().finite(p, "annual_rate", 0.0)
        tenure_months: int = int(PayloadValidator().finite(p, "tenure_months", 1))
        penalty_rate: float = PayloadValidator().finite(p, "penalty_rate", 0.0)
        as_of_str: str = p.get("as_of", "")

        as_of: date | None = None
        if as_of_str:
            try:
                as_of = date.fromisoformat(as_of_str)
            except (ValueError, TypeError):
                logger.debug("invalid as_of date '{}', using None", as_of_str)

        payments_raw: list[dict[str, Any]] = p.get("payments", [])
        payments: list[tuple[date, Decimal]] = []
        for pmt in payments_raw:
            d_str = pmt.get("date", "")
            amt = pmt.get("amount", 0)
            try:
                d = date.fromisoformat(d_str)
                payments.append((d, Decimal(str(amt))))
            except (ValueError, TypeError):
                continue

        try:
            original_schedule = generate_schedule(
                Decimal(str(principal)),
                Decimal(str(annual_rate)),
                tenure_months,
            )
            quote = calculate_foreclosure(
                Decimal(str(principal)),
                Decimal(str(annual_rate)),
                tenure_months,
                payments,
                as_of=as_of,
                penalty_rate=Decimal(str(penalty_rate)),
                original_schedule=original_schedule,
            )
        except Exception as exc:
            logger.error("foreclosure calculation failed for loan {}: {}", loan_id, exc)
            return

        self.emit(
            Type.FORECLOSURE_COMPUTED,
            {
                "loan_id": loan_id,
                "outstanding_principal": float(quote.outstanding_principal),
                "accrued_interest": float(quote.accrued_interest),
                "penalty": float(quote.penalty),
                "penalty_rate": float(quote.penalty_rate),
                "total_due": float(quote.total_due),
                "savings": float(quote.savings),
                "savings_percent": float(quote.savings_percent),
            },
            correlation_id=event.correlation_id,
        )
