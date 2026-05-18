"""Unit tests for domain event bus."""

from __future__ import annotations

import pytest

from ulu.domain.event_bus import EventBus
from ulu.domain.events import DomainEvent


class TestEventBus:
    def test_publish_and_flush(self) -> None:
        bus = EventBus()
        received = []
        bus.subscribe("test_event", lambda e: received.append(e))
        event = DomainEvent(event_type="test_event", payload={"a": 1})
        bus.publish(event)
        bus.flush()
        assert len(received) == 1
        assert received[0].event_type == "test_event"

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        handler = lambda e: None  # noqa: E731
        bus.subscribe("test_event", handler)
        bus.unsubscribe("test_event", handler)
        event = DomainEvent(event_type="test_event", payload={})
        bus.publish(event)
        bus.flush()
        assert bus.get_history() == [event]

    def test_multiple_handlers(self) -> None:
        bus = EventBus()
        called = []
        bus.subscribe("test_event", lambda e: called.append("h1"))
        bus.subscribe("test_event", lambda e: called.append("h2"))
        bus.publish(DomainEvent(event_type="test_event", payload={}))
        bus.flush()
        assert called == ["h1", "h2"]

    def test_handler_exception_not_fatal(self) -> None:
        bus = EventBus()
        called = []
        bus.subscribe("test_event", lambda e: (_ for _ in ()).throw(ValueError("boom")))
        bus.subscribe("test_event", lambda e: called.append("ok"))
        bus.publish(DomainEvent(event_type="test_event", payload={}))
        bus.flush()
        assert called == ["ok"]

    @pytest.mark.asyncio
    async def test_flush_async(self) -> None:
        bus = EventBus()
        received = []

        async def async_handler(event):
            received.append(event)

        bus.subscribe("test_event", async_handler)
        bus.publish(DomainEvent(event_type="test_event", payload={}))
        await bus.flush_async()
        assert len(received) == 1

    def test_clear_history(self) -> None:
        bus = EventBus()
        bus.publish(DomainEvent(event_type="test_event", payload={}))
        bus.flush()
        assert len(bus.get_history()) == 1
        bus.clear_history()
        assert len(bus.get_history()) == 0

    def test_clear_outbox(self) -> None:
        bus = EventBus()
        bus.publish(DomainEvent(event_type="test_event", payload={}))
        bus.clear_outbox()
        bus.flush()
        assert len(bus.get_history()) == 0
