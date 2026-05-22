"""Notification service — dispatches alerts via configurable channels."""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService


class NotificationService(NanoService):
    """Sends notifications for fraud alerts, NPA events, and early warnings.

    Currently logs to stdout; production deployments integrate with
    email / SMS / webhook providers.
    """

    def handle(self, event: Event) -> None:
        notify_types = {
            EventType.FRAUD_ALERT,
            EventType.WASH_FLAG,
            EventType.VELOCITY_FLAG,
            EventType.RISK_EARLY_WARNING,
            EventType.NPA_BUCKET_CHANGED,
            EventType.DLG_TRIGGERED,
        }
        if event.event_type in notify_types:
            self.emit(EventType.NOTIFICATION_SENT, {
                "original_event": event.event_type,
                "payload": dict(event.payload),
            },
                      correlation_id=event.correlation_id)
