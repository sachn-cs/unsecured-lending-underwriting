# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""In-process event bus implementation."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from underwrite.bus import EventBus
from underwrite.circuit import Breaker
from underwrite.dlq import Queue
from underwrite.idempotency import Guard
from underwrite.logger import logger
from underwrite.message import Message
from underwrite.rate_limit import Limiter
from underwrite.store import Store
from underwrite.subscription import Dispatcher, Registry

if TYPE_CHECKING:
    pass


# LocalBus implements EventBus structurally (Protocol) — no inheritance
# to avoid the circular import and the deallocator mismatch that
# prevents ``__bases__`` patching.
if TYPE_CHECKING:
    pass


class LocalBus:
    """Thread-safe in-process event bus with async dispatch and idempotency."""

    def __init__(
        self,
        rate_limit: float = 0.0,
        max_workers: int = 0,
        max_futures: int = 10000,
        max_buffer_size: int = 0,
        store: Store | None = None,
    ) -> None:
        """Initializes the local bus.

        Args:
            rate_limit: Max events per second per subscriber (0 = unlimited).
            max_workers: Thread pool size (0 = synchronous dispatch).
            max_futures: Max pending futures before backpressure.
            max_buffer_size: Max pending events in buffer (0 = unlimited).
            store: Optional Store for DLQ persistence.
        """
        self.lock: threading.RLock = threading.RLock()
        self.registry: Registry = Registry()
        self.buffer: deque[Message] = deque()
        self.running: bool = True
        self.started: bool = False
        self.dlq: Queue = Queue(store=store)
        self.idempotency: Guard = Guard()
        self.circuit_breaker: Breaker = Breaker()
        self.max_buffer_size: int = max_buffer_size
        self.rate_limiter: Limiter | None = Limiter(rate_limit) if rate_limit > 0 else None
        self.dispatcher: Dispatcher = Dispatcher(max_workers, max_futures)



    def publish(self, event: Message) -> str:
        """Publishes an event to all matching subscribers.

        Buffers the event and flushes immediately if the bus is running.

        Args:
            event: The event to publish.

        Returns:
            The event ID.
        """
        with self.lock:
            if self.max_buffer_size > 0 and len(self.buffer) >= self.max_buffer_size:
                dropped = self.buffer.popleft()
                logger.warning("buffer full, dropping oldest event {} ({})", dropped.event_id, dropped.event_type)
            self.buffer.append(event)
            if self.running:
                self.flush()
        return event.event_id

    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str:
        """Registers a handler for a given event type.

        Args:
            event_type: Type to subscribe to (``"*"`` for all).
            handler: Callback receiving the event.

        Returns:
            Subscription ID for use with ``unsubscribe``.
        """
        return self.registry.subscribe(event_type, handler)

    def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription.

        Args:
            subscription_id: The ID returned by ``subscribe``.
        """
        self.registry.unsubscribe(subscription_id)

    def is_stopped(self) -> bool:
        """Returns True when the bus has been explicitly stopped via ``stop()``.

        A freshly constructed bus is considered running (``is_stopped()`` returns
        ``False``) so that subscribers attached before ``start()`` can still
        dispatch once the runtime begins publishing.
        """
        with self.lock:
            return not self.running

    def subscriber_count(self, event_type: str | None = None) -> int:
        """Returns the number of registered subscribers.

        Args:
            event_type: If provided, count only subscribers to that event type;
                pass ``"*"`` for the wildcard bucket, or ``None`` for the total.
        """
        return self.registry.count(event_type)

    def start(self) -> None:
        """Starts the bus and flushes any buffered events.

        Idempotent: calling ``start()`` more than once is a no-op beyond the
        initial flush of any buffered events.
        """
        with self.lock:
            already_started = self.started
            self.running = True
            self.started = True
        if not already_started:
            self.flush()

    def stop(self) -> None:
        """Stops the bus, clears handlers and buffer, and shuts down the executor."""
        with self.lock:
            self.running = False
            self.registry.clear()
            self.buffer.clear()
        self.dispatcher.shutdown()

    def flush(self) -> None:
        pending: deque[Message] = self.buffer
        self.buffer = deque()
        for event in pending:
            handlers = self.registry.handlers_for(event.event_type)
            for sid, handler in handlers:
                if not self.circuit_breaker.allow_request(sid):
                    logger.warning("circuit open for subscriber {}, sending {} to DLQ", sid, event.event_type)
                    self.dlq.put(event, "circuit_open", sid)
                    continue
                if self.rate_limiter and not self.rate_limiter.check(f"sub:{sid}"):
                    self.dlq.put(event, "rate_limited", sid)
                    continue
                if self.dispatcher.has_executor():
                    self.dispatcher.submit(self.dispatch, handler, event, sid)
                else:
                    self.dispatch_sync(handler, event, sid)

    def dispatch_sync(self, handler: Callable[[Message], None], event: Message, sid: str) -> None:
        try:
            handler(event)
            self.circuit_breaker.record_success(sid)
        except Exception as exc:
            logger.exception("subscriber {} failed on {} ({}), sent to DLQ", sid, event.event_type, exc)
            self.dlq.put(event, f"{type(exc).__name__}: {exc}", sid)
            self.circuit_breaker.record_failure(sid)

    def dispatch(self, handler: Callable[[Message], None], event: Message, sid: str) -> None:
        try:
            handler(event)
            self.circuit_breaker.record_success(sid)
        except Exception as exc:
            logger.exception("subscriber {} failed on {} ({}), sent to DLQ", sid, event.event_type, exc)
            self.dlq.put(event, f"{type(exc).__name__}: {exc}", sid)
            self.circuit_breaker.record_failure(sid)


# Register LocalBus as a virtual subclass of EventBus (avoids the
# deallocator-mismatch error from __bases__ assignment; ABC.register
# is the standard pattern for breaking the abstract-base / concrete cycle).
EventBus.register(LocalBus)
