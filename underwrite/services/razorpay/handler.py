"""Razorpay payment gateway service.

Integrates with Razorpay for payment collection via:
  - Payment orders (one-time)
  - Payment links (shareable)
  - Subscriptions (UPI Autopay recurring)
  - e-NACH mandates (electronic mandates)
  - Webhook processing (payment success/failure)

Emits domain events for each lifecycle transition so downstream
services (payment, servicing, notification) can react.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from underwrite.__constants__ import PAISE_PER_RUPEE
from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.services.base import StatefulService
from underwrite.services.persistence import BatchedStoreRepository
from underwrite.services.razorpay.client import (
    HttpRazorpayClient,
    MockRazorpayClient,
    RazorpayClient,
    RazorpayError,
)
from underwrite.validate import get_finite

DEFAULT_RAZORPAY_API_BASE_URL: str = "https://api.razorpay.com/v1"


@dataclass(frozen=True, slots=True)
class RazorpayConfig:
    """Typed configuration for RazorpayHandler.

    Replaces the previous
    ``{k: kwargs.pop(k) for k in ...}`` dict-comprehension pattern:
    callers now pass a RazorpayConfig (or its fields are extracted
    from kwargs via a constructor that does not mutate the caller's
    mapping).
    """

    key_id: str = ""
    key_secret: str = ""
    webhook_secret: str = ""
    api_base_url: str = DEFAULT_RAZORPAY_API_BASE_URL
    timeout_seconds: int = 30


class RazorpayHandler(StatefulService):
    """Manages Razorpay order/subscription/payment lifecycle.

    Handles creation of payment orders (one-time), payment links,
    recurring subscriptions (UPI Autopay), e-NACH mandates, and
    processing of webhook events for payment confirmation.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Razorpay service.

        Args:
            key_id: Razorpay API key ID.
            key_secret: Razorpay API key secret.
            webhook_secret: Secret for webhook signature verification.
            api_base_url: Base URL for Razorpay API.
            timeout_seconds: HTTP request timeout.
        """
        config = RazorpayConfig(
            key_id=kwargs.pop("key_id", ""),
            key_secret=kwargs.pop("key_secret", ""),
            webhook_secret=kwargs.pop("webhook_secret", ""),
            api_base_url=kwargs.pop("api_base_url", DEFAULT_RAZORPAY_API_BASE_URL),
            timeout_seconds=kwargs.pop("timeout_seconds", 30),
        )
        super().__init__(**kwargs)
        self.__client: RazorpayClient = self.build_client(
            key_id=config.key_id,
            key_secret=config.key_secret,
            webhook_secret=config.webhook_secret,
            api_base_url=config.api_base_url,
        )
        self.__records: dict[str, dict[str, Any]] = {}
        self.repo: BatchedStoreRepository[dict[str, dict[str, Any]]] = self.batched_repo(
            "razorpay", dict, sync_interval=10
        )
        loaded = self.repo.load(default={})
        if loaded:
            self.__records = loaded

        self.handlers: dict[str, Any] = {
            EventType.RAZORPAY_ORDER_CREATE: self.__on_order_create,
            EventType.RAZORPAY_SUBSCRIBE: self.__on_subscription_create,
            EventType.RAZORPAY_WEBHOOK_RECEIVED: self.__on_webhook_received,
        }

    def build_client(self, **kwargs: Any) -> RazorpayClient:
        """Build the Razorpay client based on available credentials.

        Subclasses can override to inject a custom client.

        Args:
            key_id: Razorpay API key ID.
            key_secret: Razorpay API key secret.
            webhook_secret: Secret for webhook verification.
            api_base_url: Base URL for Razorpay API.

        Returns:
            A configured RazorpayClient instance (real or mock).
        """
        key_id = kwargs.get("key_id", "") or ""
        key_secret = kwargs.get("key_secret", "") or ""
        if key_id and key_secret:
            return HttpRazorpayClient(
                key_id=key_id,
                key_secret=key_secret,
                webhook_secret=kwargs.get("webhook_secret", "") or "",
                api_base_url=kwargs.get("api_base_url", "https://api.razorpay.com/v1"),
            )
        logger.info("no Razorpay credentials configured, using mock client")
        return MockRazorpayClient()

    @property
    def client(self) -> RazorpayClient:
        """Expose the underlying client for testing."""
        return self.__client

    def handle(self, event: Event) -> None:
        """Dispatch an event to the appropriate handler.

        Args:
            event: The incoming domain event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_order_create(self, event: Event) -> None:
        """Handle a RAZORPAY_ORDER_CREATE event.

        Creates a Razorpay payment order and emits RAZORPAY_ORDER_CREATED.

        Args:
            event: The RAZORPAY_ORDER_CREATE event.
        """
        p = event.payload
        loan_id: str = p.get("loan_id", "")
        if not loan_id:
            logger.warning("RAZORPAY_ORDER_CREATE missing loan_id, skipped")
            return
        amount_paise: int = int(get_finite(p, "amount", 0.0) * 100)
        currency: str = p.get("currency", "INR")
        receipt: str = p.get("receipt", f"loan_{loan_id}")
        notes: dict[str, str] = {"loan_id": loan_id}

        try:
            order = self.__client.create_order(
                amount=amount_paise,
                currency=currency,
                receipt=receipt,
                notes=notes,
            )
        except RazorpayError as exc:
            logger.error("failed to create Razorpay order for loan {}: {}", loan_id, exc)
            return

        self.save_record(
            order.id,
            {
                "type": "order",
                "loan_id": loan_id,
                "order_id": order.id,
                "amount_paise": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "status": order.status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.emit(
            EventType.RAZORPAY_ORDER_CREATED,
            {
                "loan_id": loan_id,
                "order_id": order.id,
                "amount": amount_paise / PAISE_PER_RUPEE,
                "currency": currency,
                "status": order.status,
            },
            correlation_id=event.correlation_id,
        )

    def __on_subscription_create(self, event: Event) -> None:
        """Handle a RAZORPAY_SUBSCRIBE event.

        Creates a Razorpay subscription and emits RAZORPAY_SUBSCRIPTION_CREATED.

        Args:
            event: The RAZORPAY_SUBSCRIBE event.
        """
        p = event.payload
        loan_id: str = p.get("loan_id", "")
        if not loan_id:
            logger.warning("RAZORPAY_SUBSCRIBE missing loan_id, skipped")
            return
        plan_id: str = p.get("plan_id", "") or ""
        if not plan_id:
            logger.warning("RAZORPAY_SUBSCRIBE missing plan_id")
            return
        total_count: int = int(get_finite(p, "total_count", 12))
        notes: dict[str, str] = {"loan_id": loan_id}

        try:
            sub = self.__client.create_subscription(
                plan_id=plan_id,
                total_count=total_count,
                customer_notify=True,
                notes=notes,
            )
        except RazorpayError as exc:
            logger.error("failed to create Razorpay subscription for loan {}: {}", loan_id, exc)
            return

        self.save_record(
            sub.id,
            {
                "type": "subscription",
                "loan_id": loan_id,
                "subscription_id": sub.id,
                "plan_id": plan_id,
                "status": sub.status,
                "total_count": total_count,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.emit(
            EventType.RAZORPAY_SUBSCRIPTION_CREATED,
            {
                "loan_id": loan_id,
                "subscription_id": sub.id,
                "plan_id": plan_id,
                "status": sub.status,
                "total_count": total_count,
            },
            correlation_id=event.correlation_id,
        )

    def __on_webhook_received(self, event: Event) -> None:
        """Process an incoming Razorpay webhook event.

        Validates the signature against the configured client secret
        (not a value from the untrusted payload) before processing the
        payload. Emits the appropriate domain event (captured, failed,
        refunded).
        """
        p = event.payload
        payload_bytes_str: str = p.get("payload", "")
        signature: str = p.get("signature", "")

        if not payload_bytes_str or not signature:
            logger.warning("webhook missing payload or signature, skipped")
            return

        configured_secret = self.__client.webhook_secret() if hasattr(self.__client, "webhook_secret") else None
        if not configured_secret:
            logger.error("razorpay webhook secret not configured; rejecting webhook")
            return

        payload_bytes = payload_bytes_str.encode("utf-8")
        valid = self.__client.verify_webhook(payload_bytes, signature, configured_secret)
        if not valid:
            logger.warning("invalid webhook signature, dropped")
            return

        try:
            data = json.loads(payload_bytes_str)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("invalid webhook JSON payload: {}", exc)
            return

        event_type = data.get("event", "")
        payment_data = data.get("payload", {}).get("payment", {}).get("entity", {})
        subscription_data = data.get("payload", {}).get("subscription", {}).get("entity", {})

        payment_id: str = payment_data.get("id", "")
        order_id: str = payment_data.get("order_id", "")
        subscription_id: str = subscription_data.get("id", "")
        amount_paise: int = payment_data.get("amount", 0)

        loan_id: str = (payment_data.get("notes", {}) or {}).get("loan_id", "")
        if not loan_id:
            loan_id = (subscription_data.get("notes", {}) or {}).get("loan_id", "")

        is_payment_event = event_type.startswith("payment.") or event_type.startswith("refund.")
        if is_payment_event and not payment_data:
            logger.warning("webhook missing payment entity")
            return

        if is_payment_event and not loan_id:
            logger.debug("webhook payment without loan_id, ignoring")
            return

        is_sub_event = event_type.startswith("subscription.")
        if is_sub_event and not subscription_data:
            logger.warning("webhook missing subscription entity")
            return

        if is_sub_event and not loan_id:
            logger.debug("webhook subscription without loan_id, ignoring")
            return

        if event_type == "payment.captured":
            self.on_payment_captured(
                loan_id,
                payment_id,
                order_id,
                amount_paise,
                payment_data,
                event.correlation_id,
            )
        elif event_type == "payment.failed":
            self.on_payment_failed(
                loan_id,
                payment_id,
                order_id,
                amount_paise,
                payment_data,
                event.correlation_id,
            )
        elif event_type in ("payment.refunded", "refund.created"):
            self.on_payment_refunded(
                loan_id,
                payment_id,
                order_id,
                amount_paise,
                payment_data,
                event.correlation_id,
            )
        elif event_type == "subscription.charged":
            self.on_subscription_charged(
                loan_id,
                subscription_id,
                amount_paise,
                payment_data,
                event.correlation_id,
            )
        elif event_type == "subscription.failed":
            self.on_subscription_failed(loan_id, subscription_id, payment_data, event.correlation_id)
        elif event_type == "subscription.activated":
            self.on_mandate_active(loan_id, subscription_id, event.correlation_id)
        elif event_type in ("subscription.deactivated", "subscription.cancelled"):
            self.on_mandate_inactive(loan_id, subscription_id, event.correlation_id)

    def on_payment_captured(
        self,
        loan_id: str,
        payment_id: str,
        order_id: str,
        amount_paise: int,
        payment_data: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Emit a RAZORPAY_PAYMENT_CAPTURED event.

        Args:
            loan_id: The loan identifier.
            payment_id: The Razorpay payment ID.
            order_id: The Razorpay order ID.
            amount_paise: Amount in paise.
            payment_data: Raw payment entity data.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_PAYMENT_CAPTURED,
            {
                "loan_id": loan_id,
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": amount_paise / PAISE_PER_RUPEE,
                "method": payment_data.get("method", ""),
            },
            correlation_id=correlation_id,
        )

    def on_payment_failed(
        self,
        loan_id: str,
        payment_id: str,
        order_id: str,
        amount_paise: int,
        payment_data: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Emit a RAZORPAY_PAYMENT_FAILED event.

        Args:
            loan_id: The loan identifier.
            payment_id: The Razorpay payment ID.
            order_id: The Razorpay order ID.
            amount_paise: Amount in paise.
            payment_data: Raw payment entity data.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_PAYMENT_FAILED,
            {
                "loan_id": loan_id,
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": amount_paise / PAISE_PER_RUPEE,
                "error_code": payment_data.get("error_code", ""),
                "error_description": payment_data.get("error_description", ""),
            },
            correlation_id=correlation_id,
        )

    def on_payment_refunded(
        self,
        loan_id: str,
        payment_id: str,
        order_id: str,
        amount_paise: int,
        payment_data: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Emit a RAZORPAY_PAYMENT_REFUNDED event.

        Args:
            loan_id: The loan identifier.
            payment_id: The Razorpay payment ID.
            order_id: The Razorpay order ID.
            amount_paise: Amount in paise.
            payment_data: Raw payment entity data.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_PAYMENT_REFUNDED,
            {
                "loan_id": loan_id,
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": amount_paise / PAISE_PER_RUPEE,
            },
            correlation_id=correlation_id,
        )

    def on_subscription_charged(
        self,
        loan_id: str,
        subscription_id: str,
        amount_paise: int,
        payment_data: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Emit a RAZORPAY_SUBSCRIPTION_CHARGED event.

        Args:
            loan_id: The loan identifier.
            subscription_id: The Razorpay subscription ID.
            amount_paise: Amount in paise.
            payment_data: Raw payment entity data.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_SUBSCRIPTION_CHARGED,
            {
                "loan_id": loan_id,
                "subscription_id": subscription_id,
                "payment_id": payment_data.get("id", ""),
                "amount": amount_paise / PAISE_PER_RUPEE,
            },
            correlation_id=correlation_id,
        )

    def on_subscription_failed(
        self,
        loan_id: str,
        subscription_id: str,
        payment_data: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Emit a RAZORPAY_SUBSCRIPTION_FAILED event.

        Args:
            loan_id: The loan identifier.
            subscription_id: The Razorpay subscription ID.
            payment_data: Raw payment entity data.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_SUBSCRIPTION_FAILED,
            {
                "loan_id": loan_id,
                "subscription_id": subscription_id,
                "payment_id": payment_data.get("id", ""),
                "error_code": payment_data.get("error_code", ""),
                "error_description": payment_data.get("error_description", ""),
            },
            correlation_id=correlation_id,
        )

    def on_mandate_active(self, loan_id: str, subscription_id: str, correlation_id: str) -> None:
        """Emit a RAZORPAY_MANDATE_ACTIVE event.

        Args:
            loan_id: The loan identifier.
            subscription_id: The Razorpay subscription ID.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_MANDATE_ACTIVE,
            {
                "loan_id": loan_id,
                "subscription_id": subscription_id,
                "status": "active",
            },
            correlation_id=correlation_id,
        )

    def on_mandate_inactive(self, loan_id: str, subscription_id: str, correlation_id: str) -> None:
        """Emit a RAZORPAY_MANDATE_INACTIVE event.

        Args:
            loan_id: The loan identifier.
            subscription_id: The Razorpay subscription ID.
            correlation_id: Correlation ID for tracing.
        """
        self.emit(
            EventType.RAZORPAY_MANDATE_INACTIVE,
            {
                "loan_id": loan_id,
                "subscription_id": subscription_id,
                "status": "inactive",
            },
            correlation_id=correlation_id,
        )

    def save_record(self, key: str, record: dict[str, Any]) -> None:
        """Persist a Razorpay record to the store.

        Args:
            key: Record identifier.
            record: Record data to persist.
        """
        with self.state_lock:
            store_key = f"razorpay:{key}"
            self.store.set(store_key, record)
            self.__records[store_key] = record
            self.repo.incr_and_maybe_sync(self.__records)

    def health_check(self) -> dict[str, Any]:
        """Return health metrics including Razorpay record count.

        Returns:
            Dict with base health info plus Razorpay record count.
        """
        with self.state_lock:
            return {
                **super().health_check(),
                "razorpay_records": len(self.__records),
            }
