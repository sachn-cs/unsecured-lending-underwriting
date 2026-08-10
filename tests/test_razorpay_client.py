# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for the Razorpay client layer."""

from __future__ import annotations

import pytest

from underwrite.services.razorpay.client import (
    MockRazorpayClient,
    RazorpayAuthError,
    RazorpayNotFoundError,
    RazorpayPayment,
    RazorpayValidationError,
)


class TestMockRazorpayClient:
    @pytest.fixture
    def client(self) -> MockRazorpayClient:
        return MockRazorpayClient()

    def test_create_order(self, client: MockRazorpayClient) -> None:
        order = client.create_order(amount=100000, currency="INR", receipt="test_001")
        assert order.id.startswith("order_")
        assert order.amount == 100000
        assert order.currency == "INR"
        assert order.receipt == "test_001"
        assert order.status == "created"

    def test_create_order_with_notes(self, client: MockRazorpayClient) -> None:
        order = client.create_order(amount=50000, receipt="test_002", notes={"loan_id": "L1"})
        assert order.notes.get("loan_id") == "L1"

    def test_capture_payment(self, client: MockRazorpayClient) -> None:
        payment = RazorpayPayment(
            id="pay_1",
            order_id="order_1",
            amount=100000,
            currency="INR",
            status="authorized",
            method="upi",
            email="test@example.com",
            contact="+919900000000",
            created_at=0,
        )
        client.payments["pay_1"] = payment
        captured = client.capture_payment("pay_1", 100000)
        assert captured.status == "captured"
        assert captured.captured is True

    def test_capture_nonexistent_payment(self, client: MockRazorpayClient) -> None:
        with pytest.raises(RazorpayNotFoundError):
            client.capture_payment("pay_nonexistent", 1000)

    def test_fetch_payment(self, client: MockRazorpayClient) -> None:
        payment = RazorpayPayment(
            id="pay_2",
            order_id="order_2",
            amount=50000,
            currency="INR",
            status="captured",
            method="card",
            email="a@b.com",
            contact="+919911111111",
            created_at=0,
        )
        client.payments["pay_2"] = payment
        payment = client.fetch_payment("pay_2")
        assert payment.id == "pay_2"
        assert payment.amount == 50000

    def test_fetch_nonexistent_payment(self, client: MockRazorpayClient) -> None:
        with pytest.raises(RazorpayNotFoundError):
            client.fetch_payment("pay_nonexistent")

    def test_create_subscription(self, client: MockRazorpayClient) -> None:
        sub = client.create_subscription(plan_id="plan_1", total_count=12)
        assert sub.id.startswith("sub_")
        assert sub.plan_id == "plan_1"
        assert sub.total_count == 12
        assert sub.status == "created"
        assert sub.remaining_count == 12

    def test_create_subscription_with_notes(self, client: MockRazorpayClient) -> None:
        sub = client.create_subscription(
            plan_id="plan_2",
            total_count=6,
            notes={"loan_id": "L2"},
        )
        assert sub.notes.get("loan_id") == "L2"

    def test_create_payment_link(self, client: MockRazorpayClient) -> None:
        link = client.create_payment_link(
            amount=100000,
            description="Loan repayment",
            customer={
                "name": "Alice",
                "email": "alice@example.com",
                "contact": "+919900000000",
            },
        )
        assert link.id.startswith("link_")
        assert link.short_url.startswith("https://rzp.io/")
        assert link.amount == 100000

    def test_refund_payment(self, client: MockRazorpayClient) -> None:
        payment = RazorpayPayment(
            id="pay_3",
            order_id="order_3",
            amount=100000,
            currency="INR",
            status="captured",
            method="upi",
            email="test@test.com",
            contact="+919922222222",
            created_at=0,
        )
        client.payments["pay_3"] = payment
        refund = client.refund_payment("pay_3")
        assert refund["status"] == "processed"
        assert refund["payment_id"] == "pay_3"
        assert len(client.refunds) == 1

    def test_refund_nonexistent_payment(self, client: MockRazorpayClient) -> None:
        with pytest.raises(RazorpayNotFoundError):
            client.refund_payment("pay_nonexistent")

    def test_verify_webhook_valid(self, client: MockRazorpayClient) -> None:
        import hashlib
        import hmac

        payload = b'{"event":"payment.captured"}'
        secret = "webhook_secret_123"
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        assert client.verify_webhook(payload, expected, secret) is True

    def test_verify_webhook_invalid(self, client: MockRazorpayClient) -> None:
        payload = b'{"event":"payment.captured"}'
        assert client.verify_webhook(payload, "bad_signature", "secret") is False

    def test_fail_on_create_order(self, client: MockRazorpayClient) -> None:
        client.fail_on["create_order"] = RazorpayValidationError("test error")
        with pytest.raises(RazorpayValidationError):
            client.create_order(amount=1000)

    def test_fail_on_capture(self, client: MockRazorpayClient) -> None:
        client.fail_on["capture_payment"] = RazorpayAuthError("unauthorized")
        with pytest.raises(RazorpayAuthError):
            client.capture_payment("pay_1", 1000)

    def test_multiple_orders_unique_ids(self, client: MockRazorpayClient) -> None:
        o1 = client.create_order(amount=1000)
        o2 = client.create_order(amount=2000)
        assert o1.id != o2.id

    def test_payment_link_creation_with_notes(self, client: MockRazorpayClient) -> None:
        link = client.create_payment_link(
            amount=50000,
            notes={"loan_id": "L3"},
        )
        assert link.notes.get("loan_id") == "L3"
