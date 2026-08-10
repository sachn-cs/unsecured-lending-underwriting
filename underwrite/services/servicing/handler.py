# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Loan servicing service.

Manages the post-origination lifecycle of loans: tracks active loans,
status transitions, daily interest accrual (actual/365), and coordinates
with payment, collection, and settlement services.  Also tracks Razorpay
order and mandate references against loan records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.constants import DAYS_PER_YEAR, MONEY_QUANTUM
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Core, Dependencies
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator

RATE_PERCENT_MULTIPLIER: int = 100 * DAYS_PER_YEAR


class Handler(Core):
    """Tracks active loan state, status transitions, and outstanding balances.

    Uses actual/365 daily interest accrual for accurate outstanding
    tracking. Each loan record includes:
      - ``principal``: original loan amount
      - ``outstanding``: current principal outstanding
      - ``annual_rate``: annual interest rate in percent
      - ``daily_rate``: annual_rate / 36500
      - ``last_interest_date``: last date interest was accrued to
      - ``status``: active / paid / defaulted
      - ``origin_date``: date of disbursement
      - ``razorpay_order_id``: (optional) associated Razorpay order
      - ``razorpay_mandate_status``: (optional) mandate status
    """

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
    ) -> None:
        deps = Dependencies(
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
        super().__init__(
            name=name,
            bus=deps.bus,
            store=deps.store,
            metrics=deps.metrics,
            health=deps.health,
            authz=deps.authz,
            tracer=deps.tracer,
            saga=deps.saga,
            supervisor=deps.supervisor,
            secrets_manager=deps.secrets_manager,
            max_concurrent=deps.max_concurrent,
        )
        self.handlers: dict[str, Any] = {
            Type.LOAN_ORIGINATED: self.__on_loan_originated,
            Type.REPAID: self.__on_repaid,
            Type.DEFAULT_OCCURRED: self.__on_default_occurred,
            Type.RAZORPAY_ORDER_CREATED: self.__on_razorpay_order_created,
            Type.RAZORPAY_MANDATE_ACTIVE: self.__on_mandate_active,
            Type.RAZORPAY_MANDATE_INACTIVE: self.__on_mandate_inactive,
        }

    def handle(self, event: Message) -> None:
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_loan_originated(self, event: Message) -> None:
        """Create a loan record when a loan is originated.

        Args:
            event: The LOAN_ORIGINATED event.
        """
        loan_id: str = event.payload.get("loan_id", "")
        borrower: str = event.payload.get("borrower", "")
        principal: float = PayloadValidator().finite(event.payload, "principal", 0.0)
        annual_rate: float = PayloadValidator().finite(event.payload, "annual_rate", 0.0)
        if not loan_id:
            logger.warning("dropping LOAN_ORIGINATED with missing loan_id")
            return
        principal_dec: Decimal = Decimal(str(principal))
        rate_dec: Decimal = Decimal(str(annual_rate)) / Decimal(RATE_PERCENT_MULTIPLIER)
        now = datetime.now(timezone.utc)
        self.store.set(
            f"loan:{loan_id}",
            {
                "borrower": borrower,
                "principal": float(principal_dec),
                "outstanding": float(principal_dec),
                "annual_rate": annual_rate,
                "daily_rate": float(rate_dec),
                "principal_decimal": str(principal_dec),
                "daily_rate_decimal": str(rate_dec),
                "last_interest_date": now.isoformat(),
                "origin_date": now.isoformat(),
                "status": "active",
                "originated_at": now.isoformat(),
            },
        )

    def __on_repaid(self, event: Message) -> None:
        """Apply a repayment to a loan record.

        Args:
            event: The REPAID event.
        """
        loan_id = event.payload.get("loan_id", "")
        if not loan_id:
            logger.warning("dropping REPAID with missing loan_id")
            return
        amount: float = PayloadValidator().finite(event.payload, "amount", 0.0)
        if self.bus.idempotency.is_duplicate(self.service_id, event.event_id):
            logger.debug("duplicate REPAID event {} dropped", event.event_id)
            return
        with self.state_lock:
            record = self.store.get(f"loan:{loan_id}")
            if record:
                accrued = self.__accrue_interest(record)
                remaining_dec: Decimal = Decimal(str(amount))
                if accrued > 0 and remaining_dec > 0:
                    accrued_dec: Decimal = Decimal(str(accrued))
                    if remaining_dec >= accrued_dec:
                        remaining_dec -= accrued_dec
                        record["accrued_interest"] = 0.0
                    else:
                        record["accrued_interest"] = float(accrued_dec - remaining_dec)
                        remaining_dec = Decimal("0")
                if remaining_dec > 0:
                    outstanding_dec: Decimal = Decimal(str(record.get("outstanding", 0.0)))
                    record["outstanding"] = float(max(Decimal("0"), outstanding_dec - remaining_dec))
                record["last_interest_date"] = datetime.now(timezone.utc).isoformat()
                if record["outstanding"] <= 0:
                    record["status"] = "paid"
                    record["paid_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"loan:{loan_id}", record)

    def __on_default_occurred(self, event: Message) -> None:
        """Mark a loan as defaulted.

        Args:
            event: The DEFAULT_OCCURRED event.
        """
        loan_id = event.payload.get("loan_id", "")
        if not loan_id:
            logger.warning("dropping DEFAULT_OCCURRED with missing loan_id")
            return
        with self.state_lock:
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["status"] = "defaulted"
                record["last_interest_date"] = datetime.now(timezone.utc).isoformat()
                record["defaulted_at"] = datetime.now(timezone.utc).isoformat()
                self.store.set(f"loan:{loan_id}", record)

    def __on_razorpay_order_created(self, event: Message) -> None:
        """Associate a Razorpay order ID with a loan.

        Args:
            event: The RAZORPAY_ORDER_CREATED event.
        """
        loan_id = event.payload.get("loan_id", "")
        order_id = event.payload.get("order_id", "")
        if not loan_id or not order_id:
            logger.warning("dropping RAZORPAY_ORDER_CREATED with missing loan_id or order_id")
            return
        with self.state_lock:
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["razorpay_order_id"] = order_id
                self.store.set(f"loan:{loan_id}", record)

    def __on_mandate_active(self, event: Message) -> None:
        """Record an active Razorpay mandate for a loan.

        Args:
            event: The RAZORPAY_MANDATE_ACTIVE event.
        """
        loan_id = event.payload.get("loan_id", "")
        subscription_id = event.payload.get("subscription_id", "")
        if not loan_id:
            logger.warning("dropping RAZORPAY_MANDATE_ACTIVE with missing loan_id")
            return
        with self.state_lock:
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["razorpay_subscription_id"] = subscription_id
                record["razorpay_mandate_status"] = "active"
                self.store.set(f"loan:{loan_id}", record)

    def __on_mandate_inactive(self, event: Message) -> None:
        """Record an inactive Razorpay mandate for a loan.

        Args:
            event: The RAZORPAY_MANDATE_INACTIVE event.
        """
        loan_id = event.payload.get("loan_id", "")
        if not loan_id:
            logger.warning("dropping RAZORPAY_MANDATE_INACTIVE with missing loan_id")
            return
        with self.state_lock:
            record = self.store.get(f"loan:{loan_id}")
            if record:
                record["razorpay_mandate_status"] = "inactive"
                self.store.set(f"loan:{loan_id}", record)

    def accrue_interest(self, loan_id: str) -> float:
        """Manually trigger interest accrual for a loan.

        Args:
            loan_id: The loan identifier.

        Returns:
            Accrued interest amount added since last accrual.
        """
        with self.state_lock:
            record = self.store.get(f"loan:{loan_id}")
            if record:
                return self.__accrue_interest(record)
            return 0.0

    def __accrue_interest(self, record: dict[str, Any]) -> float:
        """Accrue interest from last_interest_date to now using actual/365.

        Updates the record in-place but does not save to store.

        Args:
            record: The loan record dict.

        Returns:
            The newly accrued interest amount.
        """
        last_str = record.get("last_interest_date", "")
        if not last_str:
            return 0.0
        try:
            last_dt = datetime.fromisoformat(str(last_str))
        except (ValueError, TypeError):
            return 0.0
        now = datetime.now(timezone.utc)
        if now <= last_dt:
            return 0.0
        days = (now - last_dt).days
        if days <= 0:
            return 0.0
        outstanding_str = str(record.get("outstanding", 0.0))
        daily_rate_str = str(record.get("daily_rate", 0.0))
        outstanding_dec: Decimal = Decimal(outstanding_str)
        daily_rate_dec: Decimal = Decimal(daily_rate_str)
        if outstanding_dec <= 0 or daily_rate_dec <= 0:
            return 0.0
        interest_dec: Decimal = (outstanding_dec * daily_rate_dec * Decimal(days)).quantize(
            MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        current_accrued_str = str(record.get("accrued_interest", 0.0))
        current_accrued_dec: Decimal = Decimal(current_accrued_str)
        record["accrued_interest"] = float(current_accrued_dec + interest_dec)
        record["accrued_interest_decimal"] = str(current_accrued_dec + interest_dec)
        record["last_interest_date"] = now.isoformat()
        return float(interest_dec)
