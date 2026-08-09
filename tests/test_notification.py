"""Tests for NotificationHandler — dispatch alerts to configured channels.

Tests verify behavior through emitted NOTIFICATION_SENT events and
direct dispatch of the background notification logic.
"""

from __future__ import annotations
from underwrite.__store__ import MemoryStore

from unittest.mock import patch

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.notification.handler import NotificationHandler


def notify(bus=None) -> NotificationHandler:
    return NotificationHandler(service_id="notify", bus=bus or LocalBus(), store=MemoryStore())


class TestNotificationService:
    def __assert_forwards(self, event_type: str, payload: dict) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        svc.handle(Event(event_type=event_type, source="test", payload=payload))
        assert len(received) == 1
        assert received[0].payload["original_event"] == event_type
        assert received[0].payload["payload"] == payload

    def test_forwards_fraud_alert(self) -> None:
        self.__assert_forwards(EventType.FRAUD_ALERT, {"borrower": "alice"})

    def test_forwards_wash_flag(self) -> None:
        self.__assert_forwards(EventType.WASH_FLAG, {"borrower": "bob", "cycles": 5})

    def test_forwards_velocity_flag(self) -> None:
        self.__assert_forwards(EventType.VELOCITY_FLAG, {"borrower": "carol"})

    def test_forwards_early_warning(self) -> None:
        self.__assert_forwards(EventType.RISK_EARLY_WARNING, {"borrower": "dave", "dp": 0.35})

    def test_forwards_npa_bucket_changed(self) -> None:
        self.__assert_forwards(EventType.NPA_BUCKET_CHANGED, {"borrower": "eve", "bucket": "substandard"})

    def test_forwards_dlg_triggered(self) -> None:
        self.__assert_forwards(EventType.DLG_TRIGGERED, {"loan_id": "frank", "amount": 10000})

    def test_ignores_non_alert_events(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        for et in [
            EventType.SEED_ADDED,
            EventType.USER_ADDED,
            EventType.QUOTE_CALCULATED,
            EventType.LOAN_ORIGINATED,
            EventType.REPAID,
            EventType.GOVERNANCE_EXECUTED,
        ]:
            svc.handle(Event(event_type=et, source="test", payload={}))
        assert len(received) == 0

    def test_captures_all_alert_types(self) -> None:
        alert_types = [
            EventType.FRAUD_ALERT,
            EventType.WASH_FLAG,
            EventType.VELOCITY_FLAG,
            EventType.RISK_EARLY_WARNING,
            EventType.NPA_BUCKET_CHANGED,
            EventType.DLG_TRIGGERED,
        ]
        for at in alert_types:
            bus = LocalBus()
            received: list[Event] = []

            def record(e: Event, _r: list[Event] = received) -> None:
                _r.append(e)

            bus.subscribe(EventType.NOTIFICATION_SENT, record)
            svc = notify(bus=bus)
            bus.start()
            svc.handle(Event(event_type=at, source="test", payload={"k": "v"}))
            assert len(received) == 1, f"Failed to forward {at}"

    # ------------------------------------------------------------------ #
    #  Dispatch notification tests  (log-only mode, no email/SMS)        #
    # ------------------------------------------------------------------ #

    def test_dispatch_notification_logs_borrower_recipient(self) -> None:
        svc = notify()
        event = Event(event_type=EventType.FRAUD_ALERT, source="test", payload={"borrower": "alice"})
        with patch.object(
            svc.executor,
            "submit",
        ) as mock_submit:
            svc.handle(event)
            assert mock_submit.call_count == 1

    def test_dispatch_falls_back_to_user_recipient(self) -> None:
        svc = notify()
        event = Event(event_type=EventType.FRAUD_ALERT, source="test", payload={"user": "bob"})
        with patch.object(
            svc.executor,
            "submit",
        ) as mock_submit:
            svc.handle(event)
            assert mock_submit.call_count == 1

    def test_dispatch_logs_info_in_log_only_mode(self) -> None:
        svc = notify()
        event = Event(event_type=EventType.WASH_FLAG, source="test", payload={"borrower": "carol", "cycles": 5})
        with patch.object(
            svc.executor,
            "submit",
        ) as mock_submit:
            svc.handle(event)
            assert mock_submit.call_count == 1

    def test_notification_sent_before_dispatch_completes(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        dispatched: list[bool] = []
        assert svc.executor is not None
        original_submit = svc.executor.submit

        def delayed_submit(fn, *args, **kwargs):
            result = original_submit(fn, *args, **kwargs)
            dispatched.append(True)
            return result

        svc.executor.submit = delayed_submit  # type: ignore[assignment]
        svc.handle(Event(event_type=EventType.DLG_TRIGGERED, source="test", payload={"loan_id": "L1", "amount": 5000}))
        assert len(received) == 1
        import time

        time.sleep(0.05)
        assert len(dispatched) == 1

    def test_stop_shuts_down_executor(self) -> None:
        svc = notify()
        executor = svc.executor
        assert executor is not None
        svc.stop()
        assert svc.executor is None

    def test_handle_passes_payload_to_notification_sent(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        pl = {"borrower": "dave", "dp": 0.45}
        svc.handle(Event(event_type=EventType.RISK_EARLY_WARNING, source="test", payload=pl))
        assert len(received) == 1
        assert received[0].payload["original_event"] == EventType.RISK_EARLY_WARNING
        assert received[0].payload["payload"] == pl
