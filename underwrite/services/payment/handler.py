"""Payment processing service.

Handles payment scheduling, receipt, and overdue detection.  Emits
``payment.received`` when a payment comes in, ``payment.due`` when
a payment is expected, and ``payment.overdue`` when a payment is late.

Acts as the bridge between payment-gateway events (Razorpay) and
domain-level ``payment.received`` events so downstream services
(collection, servicing, statement) don't need gateway-specific code.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import StatefulService
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator
from underwrite.value_objects import IdGenerator, Money

OVERDUE_CUTOFF_DAYS: int = 30


class Handler(StatefulService):
    """Manages payment scheduling, receipt tracking, and delinquency detection."""

    def __init__(
        self,
        name: str,
        bus: EventBus,
        store: Store,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the payment service."""
        super().__init__(
            name=name,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__clock: SystemClock = SystemClock()
        self.__id_generator: IdGenerator = IdGenerator()
        self.handlers: dict[str, Any] = {
            Type.PAYMENT_RECEIVE: self.__on_payment_receive,
            Type.PAYMENT_SCHEDULE: self.__on_payment_schedule,
            Type.PAYMENT_CHECK_OVERDUE: self.__on_payment_check_overdue,
            Type.RAZORPAY_PAYMENT_CAPTURED: self.__on_razorpay_payment_captured,
            Type.RAZORPAY_SUBSCRIPTION_CHARGED: self.__on_razorpay_subscription_charged,
            Type.RAZORPAY_PAYMENT_REFUNDED: self.__on_razorpay_payment_refunded,
        }

    def handle(self, event: Message) -> None:
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

    def __on_payment_receive(self, event: Message) -> None:
        """Record a payment received.

        Args:
            event: The PAYMENT_RECEIVE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = PayloadValidator().finite(event.payload, "amount", 0.0)
        if not loan_id or amount <= 0:
            return
        payment_id: str = f"pay_{loan_id}_{self.__id_generator.next()}"
        money: Money = self.__to_money(amount)
        receipt = {
            "loan_id": loan_id,
            "amount_paise": money.paise,
            "amount": amount,
            "received_at": self.__clock.iso(),
        }
        self.store.set(f"payment:{payment_id}", receipt)
        self.emit(
            Type.PAYMENT_RECEIVED,
            {
                "payment_id": payment_id,
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
            },
            correlation_id=event.correlation_id,
        )

    def __on_payment_schedule(self, event: Message) -> None:
        """Schedule a future payment.

        Args:
            event: The PAYMENT_SCHEDULE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        due_date: str = event.payload.get("due_date", "")
        amount: float = PayloadValidator().finite(event.payload, "amount", 0.0)
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
            Type.PAYMENT_DUE,
            {
                "loan_id": loan_id,
                "due_date": due_date,
                "amount_paise": money.paise,
                "amount": amount,
            },
            correlation_id=event.correlation_id,
        )

    def __on_payment_check_overdue(self, event: Message) -> None:
        """Check for overdue payments and emit overdue events.

        Args:
            event: The PAYMENT_CHECK_OVERDUE event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        if not loan_id:
            return
        cutoff: datetime = self.__clock.utc_now() - timedelta(days=OVERDUE_CUTOFF_DAYS)
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
                        Type.PAYMENT_OVERDUE,
                        {
                            "loan_id": loan_id,
                            "due_date": sched["due_date"],
                            "amount": sched["amount"],
                            "amount_paise": sched.get("amount_paise", 0),
                        },
                        correlation_id=event.correlation_id,
                    )

    def __on_razorpay_payment_captured(self, event: Message) -> None:
        """Bridge a Razorpay payment captured event to PAYMENT_RECEIVED.

        Args:
            event: The RAZORPAY_PAYMENT_CAPTURED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = PayloadValidator().finite(event.payload, "amount", 0.0)
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
                "received_at": self.__clock.iso(),
            },
        )
        self.emit(
            Type.PAYMENT_RECEIVED,
            {
                "payment_id": razorpay_payment_id,
                "loan_id": loan_id,
                "amount_paise": money.paise,
                "amount": amount,
                "gateway": "razorpay",
            },
            correlation_id=event.correlation_id,
        )

    def __on_razorpay_subscription_charged(self, event: Message) -> None:
        """Bridge a Razorpay subscription charge event to PAYMENT_RECEIVED.

        Args:
            event: The RAZORPAY_SUBSCRIPTION_CHARGED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = PayloadValidator().finite(event.payload, "amount", 0.0)
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
                "received_at": self.__clock.iso(),
            },
        )
        self.emit(
            Type.PAYMENT_RECEIVED,
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

    def __on_razorpay_payment_refunded(self, event: Message) -> None:
        """Record a Razorpay payment refund.

        Args:
            event: The RAZORPAY_PAYMENT_REFUNDED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        amount: float = PayloadValidator().finite(event.payload, "amount", 0.0)
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
                "refunded_at": self.__clock.iso(),
            },
        )
        logger.info(
            "razorpay payment {} refunded for loan {}: {:.2f}",
            razorpay_payment_id,
            loan_id,
            amount,
        )
