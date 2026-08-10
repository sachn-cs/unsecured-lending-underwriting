"""Tests for the RazorpayHandler."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.razorpay.handler import RazorpayHandler
from underwrite.store import MemoryStore


def svc(bus=None) -> RazorpayHandler:
    return RazorpayHandler(service_id="razorpay", bus=bus or LocalBus(), store=MemoryStore())


def _configure_webhook_secret(svc_inst, secret: str) -> None:
    """Configure the mock client's webhook secret before a test."""
    client = svc_inst.client
    if hasattr(client, "set_webhook_secret"):
        client.set_webhook_secret(secret)
    elif hasattr(client, "webhook_secret"):
        from underwrite.exceptions import ConfigurationError

        try:
            client.webhook_secret = lambda s=secret: s
        except Exception as exc:  # pragma: no cover - defensive
            raise ConfigurationError(f"cannot set webhook secret on {type(client).__name__}") from exc


class TestRazorpayServiceOrder:
    def test_create_order_missing_loan_id_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_ORDER_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type=Type.RAZORPAY_ORDER_CREATE, source="test", payload={}))
        assert len(received) == 0

    def test_create_order_emits_created(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_ORDER_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_ORDER_CREATE,
                source="test",
                payload={
                    "loan_id": "L1",
                    "amount": 10000.0,
                    "currency": "INR",
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L1"
        assert payload["amount"] == 10000.0
        assert payload["order_id"].startswith("order_")
        assert payload["status"] == "created"

    def test_create_order_stores_record(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_ORDER_CREATE,
                source="test",
                payload={
                    "loan_id": "L2",
                    "amount": 5000.0,
                },
            )
        )
        keys = svc_inst.store.keys("razorpay:order_")
        assert len(keys) >= 1

    def test_create_order_with_custom_receipt(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_ORDER_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_ORDER_CREATE,
                source="test",
                payload={"loan_id": "L3", "amount": 8884.88, "receipt": "custom_receipt_001"},
            )
        )
        assert len(received) == 1

    def test_multiple_orders(self) -> None:
        svc_inst = svc()
        for i in range(3):
            svc_inst.handle(
                Message(
                    event_type=Type.RAZORPAY_ORDER_CREATE,
                    source="test",
                    payload={
                        "loan_id": f"L{i}",
                        "amount": float(1000 * (i + 1)),
                    },
                )
            )
        keys = svc_inst.store.keys("razorpay:order_")
        assert len(keys) == 3

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_ORDER_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0


class TestRazorpayServiceSubscription:
    def test_create_subscription_missing_loan_id(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_SUBSCRIPTION_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type=Type.RAZORPAY_SUBSCRIBE, source="test", payload={}))
        assert len(received) == 0

    def test_create_subscription_missing_plan_id(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_SUBSCRIPTION_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_SUBSCRIBE,
                source="test",
                payload={
                    "loan_id": "L10",
                },
            )
        )
        assert len(received) == 0

    def test_create_subscription_emits_created(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_SUBSCRIPTION_CREATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_SUBSCRIBE,
                source="test",
                payload={
                    "loan_id": "L11",
                    "plan_id": "plan_monthly_emi",
                    "total_count": 12,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L11"
        assert payload["plan_id"] == "plan_monthly_emi"
        assert payload["total_count"] == 12
        assert payload["subscription_id"].startswith("sub_")

    def test_create_subscription_stores_record(self) -> None:
        svc_inst = svc()
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_SUBSCRIBE,
                source="test",
                payload={
                    "loan_id": "L12",
                    "plan_id": "plan_test",
                    "total_count": 6,
                },
            )
        )
        keys = svc_inst.store.keys("razorpay:sub_")
        assert len(keys) >= 1


class TestRazorpayServiceWebhook:
    def test_webhook_missing_payload_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_CAPTURED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type=Type.RAZORPAY_WEBHOOK_RECEIVED, source="test", payload={}))
        assert len(received) == 0

    def test_webhook_missing_signature_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_CAPTURED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(event_type=Type.RAZORPAY_WEBHOOK_RECEIVED, source="test", payload={"payload": '{"event":"test"}'})
        )
        assert len(received) == 0

    def test_webhook_invalid_signature_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_CAPTURED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, "secret")
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": '{"event":"test"}',
                    "signature": "bad_sig",
                },
            )
        )
        assert len(received) == 0

    def test_webhook_payment_captured(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_captured_1",
                        "order_id": "order_1",
                        "amount": 100000,
                        "currency": "INR",
                        "status": "captured",
                        "method": "upi",
                        "email": "test@test.com",
                        "contact": "+919900000000",
                        "notes": {"loan_id": "L100"},
                    }
                }
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_test"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_CAPTURED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L100"
        assert payload["payment_id"] == "pay_captured_1"
        assert payload["amount"] == 1000.0  # 100000 paise = 1000 rupees

    def test_webhook_payment_failed(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_failed_1",
                        "order_id": "order_2",
                        "amount": 50000,
                        "status": "failed",
                        "method": "card",
                        "email": "fail@test.com",
                        "contact": "+919911111111",
                        "error_code": "BAD_SSL",
                        "error_description": "Card declined",
                        "notes": {"loan_id": "L101"},
                    }
                }
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_test"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_FAILED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L101"
        assert payload["error_code"] == "BAD_SSL"
        assert payload["error_description"] == "Card declined"

    def test_webhook_payment_refunded(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "payment.refunded",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_refunded_1",
                        "order_id": "order_3",
                        "amount": 25000,
                        "status": "refunded",
                        "method": "upi",
                        "email": "refund@test.com",
                        "contact": "+919922222222",
                        "notes": {"loan_id": "L102"},
                    }
                }
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_test"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_REFUNDED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L102"

    def test_webhook_payment_without_loan_id_ignored(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_no_loan",
                        "order_id": "order_4",
                        "amount": 1000,
                        "status": "captured",
                        "notes": {},
                    }
                }
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_test"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_PAYMENT_CAPTURED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 0

    def test_webhook_subscription_charged(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "subscription.charged",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_monthly",
                        "plan_id": "plan_emi",
                        "status": "active",
                        "notes": {"loan_id": "L200"},
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_sub_charged_1",
                        "amount": 55000,
                        "status": "captured",
                    }
                },
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_sub"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_SUBSCRIPTION_CHARGED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L200"
        assert payload["amount"] == 550.0  # 55000 paise
        assert payload["payment_id"] == "pay_sub_charged_1"

    def test_webhook_subscription_failed(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "subscription.failed",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_fail_1",
                        "notes": {"loan_id": "L201"},
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_sub_fail_1",
                        "amount": 55000,
                        "status": "failed",
                        "error_code": "PAYMENT_FAILED",
                        "error_description": "Insufficient funds",
                    }
                },
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_sub"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_SUBSCRIPTION_FAILED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L201"
        assert payload["error_code"] == "PAYMENT_FAILED"

    def test_webhook_subscription_activated(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "subscription.activated",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_active_1",
                        "status": "active",
                        "notes": {"loan_id": "L202"},
                    }
                },
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_sub"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_MANDATE_ACTIVE, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L202"
        assert payload["status"] == "active"

    def test_webhook_subscription_deactivated(self) -> None:
        import hashlib
        import hmac
        import json

        payload_dict = {
            "event": "subscription.deactivated",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_inactive_1",
                        "status": "paused",
                        "notes": {"loan_id": "L203"},
                    }
                },
            },
        }
        payload_str = json.dumps(payload_dict)
        secret = "whsec_sub"
        signature = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.RAZORPAY_MANDATE_INACTIVE, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        _configure_webhook_secret(svc_inst, secret)
        svc_inst.handle(
            Message(
                event_type=Type.RAZORPAY_WEBHOOK_RECEIVED,
                source="test",
                payload={
                    "payload": payload_str,
                    "signature": signature,
                },
            )
        )
        assert len(received) == 1
        payload = received[0].payload
        assert payload["loan_id"] == "L203"
        assert payload["status"] == "inactive"


class TestRazorpayServiceHealth:
    def test_health_check(self) -> None:
        svc_inst = svc()
        health = svc_inst.health_check()
        assert "razorpay_records" in health
        assert "service_id" in health
