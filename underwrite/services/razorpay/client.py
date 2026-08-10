# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Razorpay HTTP client abstraction with mock support."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from underwrite.constants import DAYS_PER_YEAR, SECONDS_PER_DAY
from underwrite.logger import logger

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.warning(
        "httpx not installed; HttpRazorpayClient will raise RuntimeError on use. "
        "Install the 'serve' or 'razorpay' extra to enable production Razorpay calls."
    )


class RazorpayError(Exception):
    """Raised when the Razorpay API returns an error."""


class RazorpayAuthError(RazorpayError):
    """Raised on authentication/authorization failures."""


class RazorpayValidationError(RazorpayError):
    """Raised on request validation errors."""


class RazorpayNotFoundError(RazorpayError):
    """Raised when a resource is not found."""


@dataclass(frozen=True, slots=True)
class RazorpayOrder:
    """Razorpay order object."""

    id: str
    amount: int
    currency: str
    receipt: str
    status: str
    created_at: int
    attempts: int = 0
    notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RazorpayPayment:
    """Razorpay payment object."""

    id: str
    order_id: str
    amount: int
    currency: str
    status: str
    method: str
    email: str
    contact: str
    created_at: int
    captured: bool = False
    error_code: str = ""
    error_description: str = ""
    notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RazorpaySubscription:
    """Razorpay subscription object (UPI Autopay / e-NACH)."""

    id: str
    plan_id: str
    status: str
    total_count: int
    paid_count: int
    remaining_count: int
    start_at: int
    end_at: int
    created_at: int
    notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RazorpayPaymentLink:
    """Razorpay payment link object."""

    id: str
    short_url: str
    amount: int
    currency: str
    status: str
    created_at: int
    notes: dict[str, str] = field(default_factory=dict)


class RazorpayClient(ABC):
    """Abstract Razorpay API client.

    Implementations provide create_order, capture_payment, create_subscription,
    create_payment_link, refund_payment, and verify_webhook.
    """

    @abstractmethod
    def webhook_secret(self) -> str:
        """Returns the configured webhook secret used for signature verification.

        The service MUST use this value (not anything read from the
        incoming payload) to verify webhook signatures, otherwise an
        attacker who controls the payload can submit their own secret
        and bypass the HMAC check.
        """

    @abstractmethod
    def create_order(
        self,
        amount: int,
        currency: str = "INR",
        receipt: str = "",
        notes: dict[str, str] | None = None,
    ) -> RazorpayOrder:
        """Create a Razorpay order.

        Args:
            amount: Amount in paise (smallest currency unit).
            currency: Three-letter ISO currency code.
            receipt: Unique receipt identifier.
            notes: Optional key-value notes.

        Returns:
            The created RazorpayOrder.
        """

    @abstractmethod
    def capture_payment(self, payment_id: str, amount: int) -> RazorpayPayment:
        """Capture an authorized payment.

        Args:
            payment_id: Razorpay payment ID.
            amount: Amount to capture in paise.

        Returns:
            The captured RazorpayPayment.
        """

    @abstractmethod
    def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        """Fetch payment details by ID.

        Args:
            payment_id: Razorpay payment ID.

        Returns:
            The RazorpayPayment.
        """

    @abstractmethod
    def create_subscription(
        self,
        plan_id: str,
        total_count: int,
        customer_notify: bool = True,
        notes: dict[str, str] | None = None,
        start_at: int | None = None,
        expire_by: int | None = None,
    ) -> RazorpaySubscription:
        """Create a recurring subscription (UPI Autopay / e-NACH).

        Args:
            plan_id: Razorpay plan ID.
            total_count: Total number of recurring charges.
            customer_notify: Whether to notify the customer.
            notes: Optional key-value notes.
            start_at: Optional start timestamp.
            expire_by: Optional expiry timestamp.

        Returns:
            The created RazorpaySubscription.
        """

    @abstractmethod
    def create_payment_link(
        self,
        amount: int,
        currency: str = "INR",
        description: str = "",
        customer: dict[str, Any] | None = None,
        notes: dict[str, str] | None = None,
    ) -> RazorpayPaymentLink:
        """Create a payment link.

        Args:
            amount: Amount in paise.
            currency: Three-letter ISO currency code.
            description: Payment description.
            customer: Customer details dict.
            notes: Optional key-value notes.

        Returns:
            The created RazorpayPaymentLink.
        """

    @abstractmethod
    def refund_payment(
        self,
        payment_id: str,
        amount: int | None = None,
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Refund a payment (full or partial).

        Args:
            payment_id: Razorpay payment ID.
            amount: Amount to refund in paise (None = full).
            notes: Optional key-value notes.

        Returns:
            Raw refund response dict.
        """

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify a Razorpay webhook signature.

        Args:
            payload: Raw request body bytes.
            signature: Value of the ``X-Razorpay-Signature`` header.
            secret: Webhook secret.

        Returns:
            True if the signature is valid.
        """


class HttpRazorpayClient(RazorpayClient):
    """Production Razorpay client using httpx.

    Handles authentication, request/response serialisation, and error
    mapping.  Uses Basic Auth with the key_id and key_secret.
    """

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        webhook_secret: str | None = None,
        api_base_url: str = "https://api.razorpay.com/v1",
        timeout_seconds: int = 30,
    ) -> None:
        self.key_id_storage = key_id
        self.key_secret_storage = key_secret
        self.webhook_secret_storage = webhook_secret
        self.base_url_storage = api_base_url.rstrip("/")
        self.timeout_storage = timeout_seconds
        self.http_client = httpx.Client(
            auth=(self.key_id_storage, self.key_secret_storage),
            timeout=self.timeout_storage,
        )

    def webhook_secret(self) -> str:
        return self.webhook_secret_storage or ""

    def request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request to the Razorpay API.

        Args:
            method: HTTP method.
            path: API endpoint path.
            data: Request body data.

        Returns:
            Parsed JSON response.

        Raises:
            RazorpayError: On API or transport errors.
        """
        url = urljoin(self.base_url_storage + "/", path.lstrip("/"))
        try:
            if not HAS_HTTPX:
                raise RuntimeError("httpx is required for HttpRazorpayClient")
            resp = self.http_client.request(method, url, json=data)
        except httpx.TimeoutException as exc:
            raise RazorpayError(f"request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise RazorpayError(f"request failed: {exc}") from exc
        return self.handle_response(resp)

    def handle_response(self, resp: httpx.Response) -> dict[str, Any]:
        """Handle the HTTP response and map errors.

        Args:
            resp: The httpx response.

        Returns:
            Parsed JSON body.

        Raises:
            RazorpayAuthError: On 401.
            RazorpayNotFoundError: On 404.
            RazorpayValidationError: On 400.
            RazorpayError: On other errors.
        """
        try:
            body = resp.json()
        except (json.JSONDecodeError, httpx.DecodingError) as exc:
            raise RazorpayError(f"invalid JSON response ({resp.status_code}): {exc}") from exc
        if resp.status_code == 401:
            raise RazorpayAuthError(body.get("error", {}).get("description", "unauthorized"))
        if resp.status_code == 404:
            raise RazorpayNotFoundError(body.get("error", {}).get("description", "not found"))
        if resp.status_code == 400:
            raise RazorpayValidationError(body.get("error", {}).get("description", "validation error"))
        if not resp.is_success:
            raise RazorpayError(
                f"API error ({resp.status_code}): {body.get('error', {}).get('description', 'unknown')}"
            )
        return body

    def create_order(
        self,
        amount: int,
        currency: str = "INR",
        receipt: str = "",
        notes: dict[str, str] | None = None,
    ) -> RazorpayOrder:
        """Create a Razorpay order via the API.

        Args:
            amount: Amount in paise.
            currency: ISO currency code.
            receipt: Unique receipt identifier.
            notes: Optional notes.

        Returns:
            The created RazorpayOrder.
        """
        body = self.request(
            "POST",
            "/orders",
            {
                "amount": amount,
                "currency": currency,
                "receipt": receipt,
                "notes": notes or {},
            },
        )
        return RazorpayOrder(
            id=body["id"],
            amount=body["amount"],
            currency=body["currency"],
            receipt=body.get("receipt", ""),
            status=body["status"],
            created_at=body.get("created_at", 0),
            attempts=body.get("attempts", 0),
            notes=body.get("notes", {}),
        )

    def capture_payment(self, payment_id: str, amount: int) -> RazorpayPayment:
        """Capture an authorized payment via the API.

        Args:
            payment_id: Razorpay payment ID.
            amount: Amount to capture in paise.

        Returns:
            The captured RazorpayPayment.
        """
        body = self.request("POST", f"/payments/{payment_id}/capture", {"amount": amount})
        return self.parse_payment(body)

    def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        """Fetch payment details via the API.

        Args:
            payment_id: Razorpay payment ID.

        Returns:
            The RazorpayPayment.
        """
        body = self.request("GET", f"/payments/{payment_id}")
        return self.parse_payment(body)

    def create_subscription(
        self,
        plan_id: str,
        total_count: int,
        customer_notify: bool = True,
        notes: dict[str, str] | None = None,
        start_at: int | None = None,
        expire_by: int | None = None,
    ) -> RazorpaySubscription:
        """Create a recurring subscription via the API.

        Args:
            plan_id: Razorpay plan ID.
            total_count: Total number of recurring charges.
            customer_notify: Whether to notify the customer.
            notes: Optional key-value notes.
            start_at: Optional start timestamp.
            expire_by: Optional expiry timestamp.

        Returns:
            The created RazorpaySubscription.
        """
        data: dict[str, Any] = {
            "plan_id": plan_id,
            "total_count": total_count,
            "customer_notify": customer_notify,
            "notes": notes or {},
        }
        if start_at is not None:
            data["start_at"] = start_at
        if expire_by is not None:
            data["expire_by"] = expire_by
        body = self.request("POST", "/subscriptions", data)
        return RazorpaySubscription(
            id=body["id"],
            plan_id=body.get("plan_id", ""),
            status=body["status"],
            total_count=body.get("total_count", 0),
            paid_count=body.get("paid_count", 0),
            remaining_count=body.get("remaining_count", 0),
            start_at=body.get("start_at", 0),
            end_at=body.get("end_at", 0),
            created_at=body.get("created_at", 0),
            notes=body.get("notes", {}),
        )

    def create_payment_link(
        self,
        amount: int,
        currency: str = "INR",
        description: str = "",
        customer: dict[str, Any] | None = None,
        notes: dict[str, str] | None = None,
    ) -> RazorpayPaymentLink:
        """Create a payment link via the API.

        Args:
            amount: Amount in paise.
            currency: ISO currency code.
            description: Payment description.
            customer: Customer details dict.
            notes: Optional notes.

        Returns:
            The created RazorpayPaymentLink.
        """
        data: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "description": description,
            "notes": notes or {},
        }
        if customer:
            data["customer"] = customer
        body = self.request("POST", "/payment_links", data)
        return RazorpayPaymentLink(
            id=body["id"],
            short_url=body.get("short_url", ""),
            amount=body["amount"],
            currency=body["currency"],
            status=body["status"],
            created_at=body.get("created_at", 0),
            notes=body.get("notes", {}),
        )

    def refund_payment(
        self,
        payment_id: str,
        amount: int | None = None,
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Refund a payment via the API.

        Args:
            payment_id: Razorpay payment ID.
            amount: Amount to refund in paise (None = full).
            notes: Optional notes.

        Returns:
            Raw refund response dict.
        """
        data: dict[str, Any] = {}
        if amount is not None:
            data["amount"] = amount
        if notes:
            data["notes"] = notes
        return self.request("POST", f"/payments/{payment_id}/refund", data)

    def verify_webhook(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify a Razorpay webhook signature using HMAC-SHA256.

        Args:
            payload: Raw request body bytes.
            signature: Value of the ``X-Razorpay-Signature`` header.
            secret: Webhook secret.

        Returns:
            True if the signature is valid.
        """
        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_payment(self, body: dict[str, Any]) -> RazorpayPayment:
        """Parse a payment response dict into a RazorpayPayment.

        Args:
            body: The JSON response body.

        Returns:
            A RazorpayPayment instance.
        """
        return RazorpayPayment(
            id=body["id"],
            order_id=body.get("order_id", ""),
            amount=body["amount"],
            currency=body.get("currency", "INR"),
            status=body["status"],
            method=body.get("method", ""),
            email=body.get("email", ""),
            contact=body.get("contact", ""),
            created_at=body.get("created_at", 0),
            captured=body.get("captured", False),
            error_code=body.get("error_code", ""),
            error_description=body.get("error_description", ""),
            notes=body.get("notes", {}),
        )


class MockRazorpayClient(RazorpayClient):
    """In-memory mock Razorpay client for testing.

    Stores orders, payments, subscriptions, and payment links in-memory.
    Supports configurable failure modes via ``fail_on``.
    """

    def __init__(self) -> None:
        self.orders: dict[str, RazorpayOrder] = {}
        self.payments: dict[str, RazorpayPayment] = {}
        self.subscriptions: dict[str, RazorpaySubscription] = {}
        self.payment_links: dict[str, RazorpayPaymentLink] = {}
        self.refunds: list[dict[str, Any]] = []
        self.fail_on: dict[str, Exception] = {}
        self.counter: int = 0
        self.webhook_secret_storage: str = "test_webhook_secret"

    def webhook_secret(self) -> str:
        return self.webhook_secret_storage

    def set_webhook_secret(self, secret: str) -> None:
        self.webhook_secret_storage = secret

    def next_id(self, prefix: str) -> str:
        """Generate a unique test ID with the given prefix.

        Args:
            prefix: The ID prefix.

        Returns:
            A unique identifier string.
        """
        self.counter += 1
        return f"{prefix}_{self.counter}"

    def check_fail(self, action: str) -> None:
        """Check if a failure mode is set and raise it.

        Args:
            action: The action name to check.
        """
        exc = self.fail_on.get(action)
        if exc is not None:
            raise exc

    def now(self) -> int:
        """Return the current Unix timestamp.

        Returns:
            Current time as integer seconds since epoch.
        """
        return int(time.time())

    def create_order(
        self,
        amount: int,
        currency: str = "INR",
        receipt: str = "",
        notes: dict[str, str] | None = None,
    ) -> RazorpayOrder:
        """Create a mock Razorpay order.

        Args:
            amount: Amount in paise.
            currency: ISO currency code.
            receipt: Unique receipt identifier.
            notes: Optional notes.

        Returns:
            A RazorpayOrder with generated ID.
        """
        self.check_fail("create_order")
        order = RazorpayOrder(
            id=self.next_id("order"),
            amount=amount,
            currency=currency,
            receipt=receipt,
            status="created",
            created_at=self.now(),
            notes=notes or {},
        )
        self.orders[order.id] = order
        return order

    def capture_payment(self, payment_id: str, amount: int) -> RazorpayPayment:
        """Capture a mock payment.

        Args:
            payment_id: Razorpay payment ID.
            amount: Amount to capture in paise.

        Returns:
            The captured RazorpayPayment.

        Raises:
            RazorpayNotFoundError: If payment not found.
        """
        self.check_fail("capture_payment")
        payment = self.payments.get(payment_id)
        if payment is None:
            raise RazorpayNotFoundError(f"payment {payment_id} not found")
        captured = dataclasses.replace(payment, captured=True, status="captured")
        self.payments[payment_id] = captured
        return captured

    def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        """Fetch a mock payment.

        Args:
            payment_id: Razorpay payment ID.

        Returns:
            The RazorpayPayment.

        Raises:
            RazorpayNotFoundError: If payment not found.
        """
        self.check_fail("fetch_payment")
        payment = self.payments.get(payment_id)
        if payment is None:
            raise RazorpayNotFoundError(f"payment {payment_id} not found")
        return payment

    def create_subscription(
        self,
        plan_id: str,
        total_count: int,
        customer_notify: bool = True,
        notes: dict[str, str] | None = None,
        start_at: int | None = None,
        expire_by: int | None = None,
    ) -> RazorpaySubscription:
        """Create a mock subscription.

        Args:
            plan_id: Razorpay plan ID.
            total_count: Total number of recurring charges.
            customer_notify: Whether to notify the customer.
            notes: Optional notes.
            start_at: Optional start timestamp.
            expire_by: Optional expiry timestamp.

        Returns:
            A RazorpaySubscription with generated ID.
        """
        self.check_fail("create_subscription")
        now = self.now()
        sub = RazorpaySubscription(
            id=self.next_id("sub"),
            plan_id=plan_id,
            status="created",
            total_count=total_count,
            paid_count=0,
            remaining_count=total_count,
            start_at=start_at or now,
            end_at=expire_by or (now + DAYS_PER_YEAR * SECONDS_PER_DAY),
            created_at=now,
            notes=notes or {},
        )
        self.subscriptions[sub.id] = sub
        return sub

    def create_payment_link(
        self,
        amount: int,
        currency: str = "INR",
        description: str = "",
        customer: dict[str, Any] | None = None,
        notes: dict[str, str] | None = None,
    ) -> RazorpayPaymentLink:
        """Create a mock payment link.

        Args:
            amount: Amount in paise.
            currency: ISO currency code.
            description: Payment description.
            customer: Customer details dict.
            notes: Optional notes.

        Returns:
            A RazorpayPaymentLink with generated ID.
        """
        self.check_fail("create_payment_link")
        link = RazorpayPaymentLink(
            id=self.next_id("link"),
            short_url=f"https://rzp.io/i/{self.next_id('test')}",
            amount=amount,
            currency=currency,
            status="created",
            created_at=self.now(),
            notes=notes or {},
        )
        self.payment_links[link.id] = link
        return link

    def refund_payment(
        self,
        payment_id: str,
        amount: int | None = None,
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Refund a mock payment.

        Args:
            payment_id: Razorpay payment ID.
            amount: Amount to refund in paise (None = full).
            notes: Optional notes.

        Returns:
            Refund response dict.

        Raises:
            RazorpayNotFoundError: If payment not found.
        """
        self.check_fail("refund_payment")
        payment = self.payments.get(payment_id)
        if payment is None:
            raise RazorpayNotFoundError(f"payment {payment_id} not found")
        refund = {
            "id": self.next_id("rfnd"),
            "payment_id": payment_id,
            "amount": amount or payment.amount,
            "status": "processed",
            "created_at": self.now(),
            "notes": notes or {},
        }
        self.refunds.append(refund)
        self.payments[payment_id] = dataclasses.replace(payment, status="refunded")
        return refund

    def verify_webhook(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify a webhook signature using HMAC-SHA256.

        Args:
            payload: Raw request body bytes.
            signature: The signature to verify.
            secret: Webhook secret.

        Returns:
            True if the signature is valid.
        """
        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
