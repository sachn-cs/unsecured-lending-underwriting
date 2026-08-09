"""Payment processing service.

Handles payment scheduling, receipt, and overdue detection.  Emits
``payment.received`` when a payment comes in, ``payment.due`` when
a payment is expected, and ``payment.overdue`` when a payment is late.

Acts as the bridge between payment-gateway events (Razorpay) and
domain-level ``payment.received`` events so downstream services
(collection, servicing, statement) don't need gateway-specific code.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.__value_objects__ import Money
from underwrite.services.base import StatefulService
from underwrite.validate import get_finite


class PaymentHandler(StatefulService):
    """Manages payment scheduling, receipt tracking, and delinquency detection."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the payment service."""
        super().__init__(**kwargs)
        self.handlers: dict[str, Any] = {
            EventType.PAYMENT_RECEIVE: self.__on_payment_receive,
            EventType.PAYMENT_SCHEDULE: self.__on_payment_schedule,
            EventType.PAYMENT_CHECK_OVERDUE: self.__on_payment_check_overdue,
            EventType.RAZORPAY_PAYMENT_CAPTURED: self.__on_razorpay_payment_captured,
            EventType.RAZORPAY_SUBSCRIPTION_CHARGED: self.__on_razorpay_subscription_charged,
            EventType.RAZORPAY_PAYMENT_REFUNDED: self.__on_razorpay_payment_refunded,
        }

    def handle(self, event: Event) -> None:
        """Dispatch an event to the appropriate handler.

        Args:
            event: The incoming domain event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    @staticmethod
    def __to_money(amount: float) -> Money:
        return Money.from_rupees(Decimal(str(amount)))

    def __on_payment_receive(self, event: Event) -> None:
        """Record a payment received.

        Args:
            event: The PAYMENT_RECEIVE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = get_finite(event.payload, "amount", 0.0)
        if not loan_id or amount <= 0:
            return
        payment_id: str = f"pay_{loan_id}_{uuid.uuid4().hex[:12]}"
        money: Money = self.__to_money(amount)
        receipt = {
            "loan_id": loan_id,
            "amount_paise": money.paise,
            "amount": amount,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.set(f"payment:{payment_id}", receipt)
        self.emit(
            EventType.PAYMENT_RECEIVED,
            {
                "payment_id": payment_id,
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
            },
            correlation_id=event.correlation_id,
        )

    def __on_payment_schedule(self, event: Event) -> None:
        """Schedule a future payment.

        Args:
            event: The PAYMENT_SCHEDULE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        due_date: str = event.payload.get("due_date", "")
        amount: float = get_finite(event.payload, "amount", 0.0)
        if not loan_id or not due_date:
            return
        schedule_key: str = f"schedule:{loan_id}:{due_date}"
        money: Money = self.__to_money(amount)
        schedule = {
            "loan_id": loan_id,
            "due_date": due_date,
            "amount_paise": money.paise,
            "amount": amount,
            "status": "pending",
        }
        self.store.set(schedule_key, schedule)
        self.emit(
            EventType.PAYMENT_DUE,
            {
                "loan_id": loan_id,
                "due_date": due_date,
                "amount_paise": money.paise,
                "amount": amount,
            },
            correlation_id=event.correlation_id,
        )

    def __on_payment_check_overdue(self, event: Event) -> None:
        """Check for overdue payments and emit overdue events.

        Args:
            event: The PAYMENT_CHECK_OVERDUE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        if not loan_id:
            return
        cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=30)
        for key in self.store.keys(f"schedule:{loan_id}:"):
            raw = self.store.get(key)
            if raw is None:
                continue
            sched: dict[str, object] = raw
            if sched.get("status") == "pending":
                due_str = sched.get("due_date", "")
                due = datetime.fromisoformat(str(due_str))
                if due < cutoff:
                    sched["status"] = "overdue"
                    self.store.set(key, sched)
                    self.emit(
                        EventType.PAYMENT_OVERDUE,
                        {
                            "loan_id": loan_id,
                            "due_date": sched["due_date"],
                            "amount": sched["amount"],
                            "amount_paise": sched.get("amount_paise", 0),
                        },
                        correlation_id=event.correlation_id,
                    )

    def __on_razorpay_payment_captured(self, event: Event) -> None:
        """Bridge a Razorpay payment captured event to PAYMENT_RECEIVED.

        Args:
            event: The RAZORPAY_PAYMENT_CAPTURED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = get_finite(event.payload, "amount", 0.0)
        razorpay_payment_id: str = event.payload.get("payment_id", "")
        if not loan_id or amount <= 0:
            return
        money: Money = self.__to_money(amount)
        self.store.set(
            f"razorpay_payment:{razorpay_payment_id}",
            {
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
                "status": "captured",
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.emit(
            EventType.PAYMENT_RECEIVED,
            {
                "payment_id": razorpay_payment_id,
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
                "gateway": "razorpay",
            },
            correlation_id=event.correlation_id,
        )

    def __on_razorpay_subscription_charged(self, event: Event) -> None:
        """Bridge a Razorpay subscription charge event to PAYMENT_RECEIVED.

        Args:
            event: The RAZORPAY_SUBSCRIPTION_CHARGED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = get_finite(event.payload, "amount", 0.0)
        sub_id: str = event.payload.get("subscription_id", "")
        payment_id: str = event.payload.get("payment_id", "")
        if not loan_id or amount <= 0:
            return
        money: Money = self.__to_money(amount)
        self.store.set(
            f"razorpay_subscription:{payment_id}",
            {
                "loan_id": loan_id,
                "subscription_id": sub_id,
                "amount_paise": money.paise,
                "amount": amount,
                "status": "charged",
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.emit(
            EventType.PAYMENT_RECEIVED,
            {
                "payment_id": payment_id,
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
                "gateway": "razorpay",
                "subscription_id": sub_id,
            },
            correlation_id=event.correlation_id,
        )

    def __on_razorpay_payment_refunded(self, event: Event) -> None:
        """Record a Razorpay payment refund.

        Args:
            event: The RAZORPAY_PAYMENT_REFUNDED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = get_finite(event.payload, "amount", 0.0)
        razorpay_payment_id: str = event.payload.get("payment_id", "")
        if not loan_id or amount <= 0:
            return
        money: Money = self.__to_money(amount)
        self.store.set(
            f"razorpay_refund:{razorpay_payment_id}",
            {
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
                "status": "refunded",
                "refunded_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.info(
            "razorpay payment {} refunded for loan {}: {:.2f}",
            razorpay_payment_id,
            loan_id,
            amount,
        )
