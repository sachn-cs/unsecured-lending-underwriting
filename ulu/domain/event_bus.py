"""In-memory domain event bus with outbox pattern stub.

Item 87 from production roadmap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ulu.domain.events import DomainEvent
from ulu.infra.logging import logger

EventHandler = Callable[[DomainEvent], Any]


class EventBus:
    """In-memory event bus decoupling domain mutations from side effects.

    Production should replace the in-memory queue with a persistent
    message broker (Redis Streams, RabbitMQ, Kafka).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._outbox: list[DomainEvent] = []
        self._history: list[DomainEvent] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Registers a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Removes a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]

    def publish(self, event: DomainEvent) -> None:
        """Publishes event to outbox (to be flushed later)."""
        self._outbox.append(event)
        logger.debug("event_published", event_type=event.event_type)

    def flush(self) -> None:
        """Dispatches all outbox events to subscribers synchronously."""
        while self._outbox:
            event = self._outbox.pop(0)
            self._dispatch(event)

    async def flush_async(self) -> None:
        """Dispatches all outbox events asynchronously."""
        while self._outbox:
            event = self._outbox.pop(0)
            await self._dispatch_async(event)

    def _dispatch(self, event: DomainEvent) -> None:
        self._history.append(event)
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception("event_handler_failed", event_type=event.event_type)

    async def _dispatch_async(self, event: DomainEvent) -> None:
        self._history.append(event)
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("event_handler_failed", event_type=event.event_type)

    def get_history(self) -> list[DomainEvent]:
        """Returns all dispatched events (useful for testing/auditing)."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clears event history (useful in tests)."""
        self._history.clear()

    def clear_outbox(self) -> None:
        """Clears pending outbox events."""
        self._outbox.clear()
