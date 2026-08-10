"""In-process event bus implementation."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

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


# To avoid a circular import between bus.py and local.py, declare LocalBus
# without an explicit base and patch __bases__ after bus.py has loaded.
# This is the standard pattern for breaking such cycles (used in many stdlib
# modules, e.g. typing.io).
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
        self.__lock: threading.RLock = threading.RLock()
        self.__registry: Registry = Registry()
        self.__buffer: deque[Message] = deque()
        self.__running: bool = True
        self.__started: bool = False
        self.__dlq: Queue = Queue(store=store)
        self.__idempotency: Guard = Guard()
        self.__circuit_breaker: Breaker = Breaker()
        self.__max_buffer_size: int = max_buffer_size
        self.__rate_limiter: Limiter | None = Limiter(rate_limit) if rate_limit > 0 else None
        self.__dispatcher: Dispatcher = Dispatcher(max_workers, max_futures)

    @property
    def dlq(self) -> Queue:
        """Returns the dead-letter queue for this bus instance."""
        return self.__dlq

    @property
    def idempotency(self) -> Guard:
        """Returns the idempotency guard for this bus instance."""
        return self.__idempotency

    def publish(self, event: Message) -> str:
        """Publishes an event to all matching subscribers.

        Buffers the event and flushes immediately if the bus is running.

        Args:
            event: The event to publish.

        Returns:
            The event ID.
        """
        with self.__lock:
            if self.__max_buffer_size > 0 and len(self.__buffer) >= self.__max_buffer_size:
                dropped = self.__buffer.popleft()
                logger.warning("buffer full, dropping oldest event {} ({})", dropped.event_id, dropped.event_type)
            self.__buffer.append(event)
            if self.__running:
                self.__flush()
        return event.event_id

    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str:
        """Registers a handler for a given event type.

        Args:
            event_type: Type to subscribe to (``"*"`` for all).
            handler: Callback receiving the event.

        Returns:
            Subscription ID for use with ``unsubscribe``.
        """
        return self.__registry.subscribe(event_type, handler)

    def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription.

        Args:
            subscription_id: The ID returned by ``subscribe``.
        """
        self.__registry.unsubscribe(subscription_id)

    def is_stopped(self) -> bool:
        """Returns True when the bus has been explicitly stopped via ``stop()``.

        A freshly constructed bus is considered running (``is_stopped()`` returns
        ``False``) so that subscribers attached before ``start()`` can still
        dispatch once the runtime begins publishing.
        """
        with self.__lock:
            return not self.__running

    def subscriber_count(self, event_type: str | None = None) -> int:
        """Returns the number of registered subscribers.

        Args:
            event_type: If provided, count only subscribers to that event type;
                pass ``"*"`` for the wildcard bucket, or ``None`` for the total.
        """
        return self.__registry.count(event_type)

    def start(self) -> None:
        """Starts the bus and flushes any buffered events.

        Idempotent: calling ``start()`` more than once is a no-op beyond the
        initial flush of any buffered events.
        """
        with self.__lock:
            already_started = self.__started
            self.__running = True
            self.__started = True
        if not already_started:
            self.__flush()

    def stop(self) -> None:
        """Stops the bus, clears handlers and buffer, and shuts down the executor."""
        with self.__lock:
            self.__running = False
            self.__registry.clear()
            self.__buffer.clear()
        self.__dispatcher.shutdown()

    def __flush(self) -> None:
        pending: deque[Message] = self.__buffer
        self.__buffer = deque()
        for event in pending:
            handlers = self.__registry.handlers_for(event.event_type)
            for sid, handler in handlers:
                if not self.__circuit_breaker.allow_request(sid):
                    logger.warning("circuit open for subscriber {}, sending {} to DLQ", sid, event.event_type)
                    self.__dlq.put(event, "circuit_open", sid)
                    continue
                if self.__rate_limiter and not self.__rate_limiter.check(f"sub:{sid}"):
                    self.__dlq.put(event, "rate_limited", sid)
                    continue
                if self.__dispatcher.has_executor():
                    self.__dispatcher.submit(self.__dispatch, handler, event, sid)
                else:
                    self.__dispatch_sync(handler, event, sid)

    def __dispatch_sync(self, handler: Callable[[Message], None], event: Message, sid: str) -> None:
        try:
            handler(event)
            self.__circuit_breaker.record_success(sid)
        except Exception as exc:
            logger.exception("subscriber {} failed on {} ({}), sent to DLQ", sid, event.event_type, exc)
            self.__dlq.put(event, f"{type(exc).__name__}: {exc}", sid)
            self.__circuit_breaker.record_failure(sid)

    def __dispatch(self, handler: Callable[[Message], None], event: Message, sid: str) -> None:
        try:
            handler(event)
            self.__circuit_breaker.record_success(sid)
        except Exception as exc:
            logger.exception("subscriber {} failed on {} ({}), sent to DLQ", sid, event.event_type, exc)
            self.__dlq.put(event, f"{type(exc).__name__}: {exc}", sid)
            self.__circuit_breaker.record_failure(sid)
