"""Exhaustive tests for CommunicationHandler."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.communication.service import CommunicationHandler


class TestCommunicationService:
    def test_send_message_creates_record(self) -> None:
        svc = CommunicationHandler(service_id="comm")
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "alice@test.com", "subject": "Welcome", "body": "Hello"},
            )
        )
        keys = svc.store.keys("message:msg_alice@test.com_")
        assert len(keys) == 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["recipient"] == "alice@test.com"
        assert rec["subject"] == "Welcome"

    def test_send_queues_when_no_delivery_adapter(self) -> None:
        """Without a delivery adapter the service records intent but
        does NOT emit COMMUNICATION_SENT — only confirmed deliveries
        should be reported as SENT."""
        bus = LocalBus()
        received: list = []
        bus.subscribe("communication.sent", lambda e: received.append(e))
        svc = CommunicationHandler(service_id="comm", bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "bob@test.com", "subject": "Alert", "body": "Risk"},
            )
        )
        assert received == []
        keys = svc.store.keys("message:msg_bob@test.com_")
        assert len(keys) == 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["delivery_status"] == "queued"

    def test_send_with_custom_channel(self) -> None:
        svc = CommunicationHandler(service_id="comm")
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "+12345", "subject": "SMS Alert", "body": "Hi", "channel": "sms"},
            )
        )
        keys = svc.store.keys("message:")
        assert len(keys) == 1
        rec = svc.store.get(keys[0])
        assert rec is not None
        assert rec["channel"] == "sms"

    def test_rejects_empty_recipient(self) -> None:
        svc = CommunicationHandler(service_id="comm")
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "", "subject": "Test", "body": "Body"},
            )
        )
        assert len(svc.store.keys("message:")) == 0

    def test_handles_statement_generated(self) -> None:
        svc = CommunicationHandler(service_id="comm")
        svc.handle(Event(event_type=EventType.STATEMENT_GENERATED, source="test", payload={"loan_id": "L1"}))
        keys = svc.store.keys("comm_stmt:L1:")
        assert len(keys) == 1

    def test_ignores_unrelated_events(self) -> None:
        svc = CommunicationHandler(service_id="comm")
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        assert len(svc.store.keys("message:")) == 0

    def test_multiple_messages_to_same_recipient(self) -> None:
        svc = CommunicationHandler(service_id="comm")
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "same@test.com", "subject": "Msg 1", "body": "B"},
            )
        )
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "same@test.com", "subject": "Msg 2", "body": "B"},
            )
        )
        svc.handle(
            Event(
                event_type="communication.send",
                source="test",
                payload={"recipient": "same@test.com", "subject": "Msg 3", "body": "B"},
            )
        )
        assert len(svc.store.keys("message:msg_same@test.com_")) == 3
