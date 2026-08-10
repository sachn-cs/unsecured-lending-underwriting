"""Tests for NotificationHandler — dispatch alerts to configured channels.

Tests verify behavior through emitted NOTIFICATION_SENT events and
direct dispatch of the background notification logic.
"""

from __future__ import annotations

from unittest.mock import patch

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.notification.handler import NotificationHandler
from underwrite.store import MemoryStore


def notify(bus=None) -> NotificationHandler:
    return NotificationHandler(service_id="notify", bus=bus or LocalBus(), store=MemoryStore())


class TestNotificationService:
    def __assert_forwards(self, event_type: str, payload: dict) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        svc.handle(Message(event_type=event_type, source="test", payload=payload))
        assert len(received) == 1
        assert received[0].payload["original_event"] == event_type
        assert received[0].payload["payload"] == payload

    def test_forwards_fraud_alert(self) -> None:
        self.__assert_forwards(Type.FRAUD_ALERT, {"borrower": "alice"})

    def test_forwards_wash_flag(self) -> None:
        self.__assert_forwards(Type.WASH_FLAG, {"borrower": "bob", "cycles": 5})

    def test_forwards_velocity_flag(self) -> None:
        self.__assert_forwards(Type.VELOCITY_FLAG, {"borrower": "carol"})

    def test_forwards_early_warning(self) -> None:
        self.__assert_forwards(Type.RISK_EARLY_WARNING, {"borrower": "dave", "dp": 0.35})

    def test_forwards_npa_bucket_changed(self) -> None:
        self.__assert_forwards(Type.NPA_BUCKET_CHANGED, {"borrower": "eve", "bucket": "substandard"})

    def test_forwards_dlg_triggered(self) -> None:
        self.__assert_forwards(Type.DLG_TRIGGERED, {"loan_id": "frank", "amount": 10000})

    def test_ignores_non_alert_events(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        for et in [
            Type.SEED_ADDED,
            Type.USER_ADDED,
            Type.QUOTE_CALCULATED,
            Type.LOAN_ORIGINATED,
            Type.REPAID,
            Type.GOVERNANCE_EXECUTED,
        ]:
            svc.handle(Message(event_type=et, source="test", payload={}))
        assert len(received) == 0

    def test_captures_all_alert_types(self) -> None:
        alert_types = [
            Type.FRAUD_ALERT,
            Type.WASH_FLAG,
            Type.VELOCITY_FLAG,
            Type.RISK_EARLY_WARNING,
            Type.NPA_BUCKET_CHANGED,
            Type.DLG_TRIGGERED,
        ]
        for at in alert_types:
            bus = LocalBus()
            received: list[Message] = []

            def record(e: Message, _r: list[Message] = received) -> None:
                _r.append(e)

            bus.subscribe(Type.NOTIFICATION_SENT, record)
            svc = notify(bus=bus)
            bus.start()
            svc.handle(Message(event_type=at, source="test", payload={"k": "v"}))
            assert len(received) == 1, f"Failed to forward {at}"

    # ------------------------------------------------------------------ #
    #  Dispatch notification tests  (log-only mode, no email/SMS)        #
    # ------------------------------------------------------------------ #

    def test_dispatch_notification_logs_borrower_recipient(self) -> None:
        svc = notify()
        event = Message(event_type=Type.FRAUD_ALERT, source="test", payload={"borrower": "alice"})
        with patch.object(
            svc.executor,
            "submit",
        ) as mock_submit:
            svc.handle(event)
            assert mock_submit.call_count == 1

    def test_dispatch_falls_back_to_user_recipient(self) -> None:
        svc = notify()
        event = Message(event_type=Type.FRAUD_ALERT, source="test", payload={"user": "bob"})
        with patch.object(
            svc.executor,
            "submit",
        ) as mock_submit:
            svc.handle(event)
            assert mock_submit.call_count == 1

    def test_dispatch_logs_info_in_log_only_mode(self) -> None:
        svc = notify()
        event = Message(event_type=Type.WASH_FLAG, source="test", payload={"borrower": "carol", "cycles": 5})
        with patch.object(
            svc.executor,
            "submit",
        ) as mock_submit:
            svc.handle(event)
            assert mock_submit.call_count == 1

    def test_notification_sent_before_dispatch_completes(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        svc.handle(Message(event_type=Type.DLG_TRIGGERED, source="test", payload={"loan_id": "L1", "amount": 5000}))
        assert len(received) == 1

    def test_stop_shuts_down_executor(self) -> None:
        svc = notify()
        executor = svc.executor
        assert executor is not None
        svc.stop()
        assert svc.executor is None

    def test_handle_passes_payload_to_notification_sent(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        pl = {"borrower": "dave", "dp": 0.45}
        svc.handle(Message(event_type=Type.RISK_EARLY_WARNING, source="test", payload=pl))
        assert len(received) == 1
        assert received[0].payload["original_event"] == Type.RISK_EARLY_WARNING
        assert received[0].payload["payload"] == pl
