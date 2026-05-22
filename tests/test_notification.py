"""Tests for NotificationService — dispatch alerts to configured channels.

Tests verify behavior through emitted NOTIFICATION_SENT events.
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.notification.service import NotificationService


def notify(bus=None) -> NotificationService:
    return NotificationService(service_id="notify", bus=bus)


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
        self.__assert_forwards(EventType.WASH_FLAG, {
            "borrower": "bob",
            "cycles": 5
        })

    def test_forwards_velocity_flag(self) -> None:
        self.__assert_forwards(EventType.VELOCITY_FLAG, {"borrower": "carol"})

    def test_forwards_early_warning(self) -> None:
        self.__assert_forwards(EventType.RISK_EARLY_WARNING, {
            "borrower": "dave",
            "dp": 0.35
        })

    def test_forwards_npa_bucket_changed(self) -> None:
        self.__assert_forwards(EventType.NPA_BUCKET_CHANGED, {
            "borrower": "eve",
            "bucket": "substandard"
        })

    def test_forwards_dlg_triggered(self) -> None:
        self.__assert_forwards(EventType.DLG_TRIGGERED, {
            "loan_id": "frank",
            "amount": 10000
        })

    def test_ignores_non_alert_events(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.NOTIFICATION_SENT, lambda e: received.append(e))
        svc = notify(bus=bus)
        bus.start()
        for et in [
                EventType.SEED_ADDED, EventType.USER_ADDED,
                EventType.QUOTE_CALCULATED, EventType.LOAN_ORIGINATED,
                EventType.REPAID, EventType.GOVERNANCE_EXECUTED
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
            bus.subscribe(EventType.NOTIFICATION_SENT,
                          lambda e, rec=received: rec.append(e))
            svc = notify(bus=bus)
            bus.start()
            svc.handle(Event(event_type=at, source="test", payload={"k": "v"}))
            assert len(received) == 1, f"Failed to forward {at}"
