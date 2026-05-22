"""In-process event bus for nano-service communication.

This is the **local** backend — a synchronous, thread-safe, in-process
pub-sub bus.  Production deployments swap this for SQS or Modal queues
via configuration; the ``EventBus`` interface remains the same.
"""

from __future__ import annotations

__all__ = [
    "DeadLetterQueue",
    "DeadLetterRecord",
    "EventBus",
    "IdempotencyGuard",
    "LocalBus",
    "RateLimiter",
]

import concurrent.futures
import logging
import threading
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from underwrite.__events__ import Event
from underwrite.__exceptions__ import RateLimitError

logger = logging.getLogger("underwrite")


@dataclass
class DeadLetterRecord:
    """A single failed event and the error that caused the failure."""

    event: Event
    error: str
    subscriber_id: str
    timestamp: float = field(default_factory=time.time)


class DeadLetterQueue:
    """Captures events that failed processing.

    Evicts oldest entries when *max_records* is exceeded to prevent
    unbounded memory growth.
    """

    def __init__(self, max_records: int = 10000) -> None:
        """Initialises a bounded dead-letter queue.

        Args:
            max_records: Maximum entries before oldest are evicted.
        """
        self.__lock: threading.Lock = threading.Lock()
        self.__records: list[DeadLetterRecord] = []
        self.__max_records: int = max_records

    def put(self, event: Event, error: str, subscriber_id: str) -> None:
        """Records a failed event.

        Args:
            event: The event that failed.
            error: Description of the failure.
            subscriber_id: Identifier of the subscriber that failed.
        """
        with self.__lock:
            if len(self.__records) >= self.__max_records:
                self.__records.pop(0)
            self.__records.append(
                DeadLetterRecord(
                    event=event,
                    error=error,
                    subscriber_id=subscriber_id,
                ))

    @property
    def records(self) -> list[DeadLetterRecord]:
        """Returns a snapshot of all dead-letter records."""
        with self.__lock:
            return list(self.__records)

    @property
    def count(self) -> int:
        """Returns the number of dead-letter records."""
        with self.__lock:
            return len(self.__records)

    def clear(self) -> None:
        """Removes all dead-letter records."""
        with self.__lock:
            self.__records.clear()

    def replay(self, bus: EventBus, max_count: int = 0) -> int:
        """Re-publishes dead-letter events to a bus.

        Args:
            bus: The event bus to publish on.
            max_count: Maximum events to replay (0 = all).

        Returns:
            Number of events replayed.
        """
        with self.__lock:
            to_replay = list(self.__records)
            if max_count > 0:
                to_replay = to_replay[:max_count]
            self.__records = self.__records[len(to_replay):]
        for record in to_replay:
            bus.publish(record.event)
        return len(to_replay)


class RateLimiter:
    """Token-bucket rate limiter per key."""

    def __init__(self, max_rate: float = 100.0, interval: float = 1.0) -> None:
        """Initialises a token-bucket rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
        """
        self.__max_rate: float = max_rate
        self.__interval: float = interval
        self.__lock: threading.Lock = threading.Lock()
        self.__buckets: dict[str, float] = {}

    def check(self, key: str) -> bool:
        """Checks whether *key* is allowed under the rate limit.

        Args:
            key: Identifier to rate-limit (e.g. subscriber ID).

        Returns:
            True if the operation is allowed, False otherwise.
        """
        now = time.monotonic()
        with self.__lock:
            last = self.__buckets.get(key, 0.0)
            if now - last < self.__interval / self.__max_rate:
                return False
            self.__buckets[key] = now
            return True

    def assert_allowed(self, key: str) -> None:
        """Asserts that *key* is under the rate limit, raising otherwise.

        Args:
            key: Identifier to rate-limit.

        Raises:
            RateLimitError: If the rate limit is exceeded.
        """
        if not self.check(key):
            raise RateLimitError(f"rate limit exceeded for {key}")


class IdempotencyGuard:
    """Prevents duplicate event processing by tracking seen event IDs per handler."""

    def __init__(self) -> None:
        """Initialises an empty idempotency guard."""
        self.__lock: threading.Lock = threading.Lock()
        self.__seen: dict[str, set[str]] = {}

    def is_duplicate(self, handler_id: str, event_id: str) -> bool:
        """Checks whether an event has already been processed by a handler.

        Records the event ID on first check; subsequent calls for the
        same (handler, event) pair return True.

        Args:
            handler_id: Unique identifier for the handler.
            event_id: Unique event identifier.

        Returns:
            True if this event was already seen for this handler.
        """
        with self.__lock:
            seen = self.__seen.setdefault(handler_id, set())
            if event_id in seen:
                return True
            seen.add(event_id)
            return False


class EventBus(ABC):
    """Abstract event bus.  All nano services publish and subscribe here."""

    @abstractmethod
    def publish(self, event: Event) -> str:
        """Publishes an event to all matching subscribers.  Returns the event ID."""

    @abstractmethod
    def subscribe(self, event_type: str, handler: Callable[[Event],
                                                           None]) -> str:
        """Registers a handler for *event_type* (use ``*`` for wildcard).

        Returns a subscription ID that can be passed to ``unsubscribe``.
        """

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription."""

    @abstractmethod
    def start(self) -> None:
        """Starts delivering buffered events."""

    @abstractmethod
    def stop(self) -> None:
        """Stops event delivery and clears all subscriptions."""

    @property
    @abstractmethod
    def dlq(self) -> DeadLetterQueue:
        """Returns the dead-letter queue for this bus."""

    @property
    @abstractmethod
    def idempotency(self) -> IdempotencyGuard:
        """Returns the idempotency guard for this bus."""


class LocalBus(EventBus):
    """Thread-safe in-process event bus with async dispatch and idempotency."""

    def __init__(self, rate_limit: float = 0.0, max_workers: int = 0) -> None:
        """Initialises the local bus.

        Args:
            rate_limit: Max events per second per subscriber (0 = unlimited).
            max_workers: Thread pool size (0 = synchronous dispatch).
        """
        self.__lock: threading.RLock = threading.RLock()
        self.__handlers: dict[str, list[tuple[str, Callable[[Event],
                                                            None]]]] = {}
        self.__buffer: list[Event] = []
        self.__running: bool = False
        self.__dlq: DeadLetterQueue = DeadLetterQueue()
        self.__idempotency: IdempotencyGuard = IdempotencyGuard()
        self.__rate_limiter: RateLimiter | None = RateLimiter(
            rate_limit) if rate_limit > 0 else None
        self.__executor: concurrent.futures.ThreadPoolExecutor | None = (
            concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers) if max_workers > 0 else None)
        self.__futures: list[concurrent.futures.Future] = []
        self.__MAX_FUTURES: int = 10000

    @property
    def dlq(self) -> DeadLetterQueue:
        """Returns the dead-letter queue for this bus instance."""
        return self.__dlq

    @property
    def idempotency(self) -> IdempotencyGuard:
        """Returns the idempotency guard for this bus instance."""
        return self.__idempotency

    def publish(self, event: Event) -> str:
        """Publishes an event to all matching subscribers.

        Buffers the event and flushes immediately if the bus is running.

        Args:
            event: The event to publish.

        Returns:
            The event ID.
        """
        with self.__lock:
            self.__buffer.append(event)
            if self.__running:
                self.__flush()
        return event.event_id

    def subscribe(self, event_type: str, handler: Callable[[Event],
                                                           None]) -> str:
        """Registers a handler for a given event type.

        Args:
            event_type: Type to subscribe to (``"*"`` for all).
            handler: Callback receiving the event.

        Returns:
            Subscription ID for use with ``unsubscribe``.
        """
        sid = str(uuid.uuid4())
        with self.__lock:
            self.__handlers.setdefault(event_type, []).append((sid, handler))
        return sid

    def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription.

        Args:
            subscription_id: The ID returned by ``subscribe``.
        """
        with self.__lock:
            for event_type in list(self.__handlers):
                self.__handlers[event_type] = [
                    (sid, h)
                    for sid, h in self.__handlers[event_type]
                    if sid != subscription_id
                ]

    def start(self) -> None:
        """Starts the bus and flushes any buffered events."""
        with self.__lock:
            self.__running = True
            self.__flush()

    def stop(self) -> None:
        """Stops the bus, clears handlers and buffer, and shuts down the executor."""
        with self.__lock:
            self.__running = False
            self.__handlers.clear()
            self.__buffer.clear()
        if self.__executor:
            try:
                self.__executor.shutdown(wait=True, timeout=30)  # type: ignore[call-arg]
            except TimeoutError:
                logger.warning("executor shutdown timed out after 30s")
        self.__futures.clear()

    def __flush(self) -> None:
        pending, self.__buffer = self.__buffer, []
        for event in pending:
            handlers = self.__handlers.get(event.event_type,
                                           []) + self.__handlers.get("*", [])
            for sid, handler in handlers:
                if self.__rate_limiter and not self.__rate_limiter.check(
                        f"sub:{sid}"):
                    self.__dlq.put(event, "rate_limited", sid)
                    continue
                if self.__executor:
                    future = self.__executor.submit(self.__dispatch, handler,
                                                    event, sid)
                    self.__futures.append(future)
                    self.__trim_futures()
                else:
                    self.__dispatch_sync(handler, event, sid)

    def __trim_futures(self) -> None:
        if len(self.__futures) < self.__MAX_FUTURES:
            return
        done = [f for f in self.__futures if f.done()]
        for f in done:
            try:
                f.result(timeout=0)
            except Exception:
                logger.debug("future %s raised on result", f, exc_info=True)
        self.__futures = [f for f in self.__futures if not f.done()]

    def __dispatch_sync(self, handler: Callable[[Event], None], event: Event,
                        sid: str) -> None:
        try:
            handler(event)
        except Exception as exc:
            tb = traceback.format_exc()
            self.__dlq.put(event, f"{exc}\n{tb}", sid)

    def __dispatch(self, handler: Callable[[Event], None], event: Event,
                   sid: str) -> None:
        try:
            handler(event)
        except Exception as exc:
            tb = traceback.format_exc()
            self.__dlq.put(event, f"{exc}\n{tb}", sid)
