"""In-process event bus for nano-service communication.

This is the **local** backend — a synchronous, thread-safe, in-process
pub-sub bus.  Production deployments swap this for SQS or Modal queues
via configuration; the ``EventBus`` interface remains the same.
"""

from __future__ import annotations

__all__ = [
    "AsyncEventBus",
    "AsyncLocalBus",
    "DeadLetterQueue",
    "DeadLetterRecord",
    "DistributedRateLimiter",
    "EventBus",
    "IdempotencyGuard",
    "LocalBus",
    "RateLimiter",
]

import asyncio
import concurrent.futures
import logging
import threading
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from underwrite.__events__ import Event
from underwrite.__exceptions__ import RateLimitError
from underwrite.__store__ import Store

logger = logging.getLogger(__name__)


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
    unbounded memory growth.  Optionally persists to a ``Store`` for
    durability across restarts.  Persistence is batched — the store is
    only written every *sync_interval* ``put()`` calls to avoid
    O(n) serialisation overhead on every event.
    """

    def __init__(self,
                 max_records: int = 10000,
                 store: Store | None = None,
                 sync_interval: int = 10) -> None:
        """Initialises a bounded dead-letter queue.

        Args:
            max_records: Maximum entries before oldest are evicted.
            store: Optional Store backend for persistence.
            sync_interval: Persist to store only every N puts (1 = every put).
        """
        self.__lock: threading.Lock = threading.Lock()
        self.__records: list[DeadLetterRecord] = []
        self.__max_records: int = max_records
        self.__store: Store | None = store
        self.__sync_interval: int = max(sync_interval, 1)
        self.__sync_counter: int = 0
        if store is not None:
            self.__load_store()

    # -- serialisation helpers -----------------------------------------------

    @staticmethod
    def _event_to_dict(event: Event) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "source": event.source,
            "source_key": event.source_key,
            "timestamp": event.timestamp,
            "payload": event.payload,
            "correlation_id": event.correlation_id,
            "signature": event.signature,
        }

    @staticmethod
    def _event_from_dict(d: dict[str, Any]) -> Event:
        return Event(**d)

    @staticmethod
    def _record_to_dict(r: DeadLetterRecord) -> dict[str, Any]:
        return {
            "event": DeadLetterQueue._event_to_dict(r.event),
            "error": r.error,
            "subscriber_id": r.subscriber_id,
            "timestamp": r.timestamp,
        }

    @staticmethod
    def _record_from_dict(d: dict[str, Any]) -> DeadLetterRecord:
        return DeadLetterRecord(
            event=DeadLetterQueue._event_from_dict(d["event"]),
            error=d["error"],
            subscriber_id=d["subscriber_id"],
            timestamp=d["timestamp"],
        )

    # -- persistence ----------------------------------------------------------

    def __load_store(self) -> None:
        store = self.__store
        if store is None:
            return
        raw = store.get("bus:dlq")
        if raw is not None:
            if isinstance(raw, list):
                valid: list[DeadLetterRecord] = []
                skipped = 0
                for r in raw:
                    if isinstance(r, dict) and "event" in r:
                        valid.append(self._record_from_dict(r))
                    else:
                        skipped += 1
                if skipped:
                    logger.warning("skipped %d corrupted DLQ records on load",
                                   skipped)
                self.__records = valid
            else:
                logger.warning(
                    "corrupted DLQ store data (expected list, got %s), "
                    "starting with empty DLQ",
                    type(raw).__name__)

    def __sync_store(self) -> None:
        store = self.__store
        if store is None:
            return
        try:
            store.set("bus:dlq",
                      [self._record_to_dict(r) for r in self.__records])
        except Exception:
            logger.exception("failed to persist DLQ records to store")

    def __should_sync(self) -> bool:
        self.__sync_counter += 1
        if self.__sync_counter >= self.__sync_interval:
            self.__sync_counter = 0
            return True
        return False

    # -- public API -----------------------------------------------------------

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
            if self.__should_sync():
                self.__sync_store()

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
            self.__sync_counter = 0
            self.__sync_store()

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
            self.__sync_counter = 0
            self.__sync_store()
        for record in to_replay:
            bus.publish(record.event)
        return len(to_replay)


class CircuitBreaker:
    """Per-subscriber circuit breaker that stops dispatching to failing subscribers.

    Transitions: CLOSED -> OPEN (after *failure_threshold* consecutive failures)
                 OPEN -> HALF_OPEN (after *cooldown_seconds*)
                 HALF_OPEN -> CLOSED (on success) or -> OPEN (on failure)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self,
                 failure_threshold: int = 5,
                 cooldown_seconds: float = 60.0) -> None:
        self.__threshold: int = failure_threshold
        self.__cooldown: float = cooldown_seconds
        self.__lock: threading.Lock = threading.Lock()
        self.__failures: dict[str, int] = {}
        self.__state: dict[str, str] = {}
        self.__opened_at: dict[str, float] = {}

    def allow_request(self, subscriber_id: str) -> bool:
        """Returns True if the request should be allowed through."""
        with self.__lock:
            state = self.__state.get(subscriber_id, self.CLOSED)
            if state == self.CLOSED:
                return True
            if state == self.OPEN:
                opened = self.__opened_at.get(subscriber_id, 0.0)
                if time.monotonic() - opened >= self.__cooldown:
                    self.__state[subscriber_id] = self.HALF_OPEN
                    return True
                return False
            return True  # HALF_OPEN — allow probe request

    def record_failure(self, subscriber_id: str) -> None:
        """Records a failure for the subscriber. May trip circuit to OPEN."""
        with self.__lock:
            count = self.__failures.get(subscriber_id, 0) + 1
            self.__failures[subscriber_id] = count
            if count >= self.__threshold:
                self.__state[subscriber_id] = self.OPEN
                self.__opened_at[subscriber_id] = time.monotonic()

    def record_success(self, subscriber_id: str) -> None:
        """Resets failure count and closes the circuit."""
        with self.__lock:
            self.__failures.pop(subscriber_id, None)
            prev = self.__state.pop(subscriber_id, None)
            self.__opened_at.pop(subscriber_id, None)
            if prev == self.HALF_OPEN:
                logger.info("circuit breaker closed for subscriber %s",
                            subscriber_id)

    def state(self, subscriber_id: str) -> str:
        """Returns the current circuit state for the subscriber."""
        with self.__lock:
            return self.__state.get(subscriber_id, self.CLOSED)


class RateLimiter:
    """Token-bucket rate limiter per key."""

    def __init__(self, max_rate: float = 100.0, interval: float = 1.0) -> None:
        """Initialises a token-bucket rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
        """
        self._max_rate: float = max_rate
        self._interval: float = interval
        self._lock: threading.Lock = threading.Lock()
        self._buckets: dict[str, float] = {}

    def check(self, key: str) -> bool:
        """Checks whether *key* is allowed under the rate limit.

        Args:
            key: Identifier to rate-limit (e.g. subscriber ID).

        Returns:
            True if the operation is allowed, False otherwise.
        """
        if self._max_rate == 0:
            return True
        now = time.monotonic()
        with self._lock:
            last = self._buckets.get(key, 0.0)
            if now - last < self._interval / self._max_rate:
                return False
            self._buckets[key] = now
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


class DistributedRateLimiter(RateLimiter):
    """Store-backed distributed token-bucket rate limiter.

    Shares state through a common ``Store`` so that multiple processes
    (or hosts) respect the same rate limit.  Falls back to the in-memory
    parent implementation when no store is provided.
    """

    def __init__(
        self,
        max_rate: float = 100.0,
        interval: float = 1.0,
        store: Store | None = None,
        prefix: str = "ratelimit",
    ) -> None:
        """Initialises a distributed rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
            store: Shared store for cross-process coordination.
            prefix: Key prefix in the store.
        """
        super().__init__(max_rate=max_rate, interval=interval)
        self.__store: Store | None = store
        self.__prefix: str = prefix
        if store is None:
            logger.warning("DistributedRateLimiter created without store, "
                           "falling back to in-memory rate limiter")

    def check(self, key: str) -> bool:
        if self.__store is None:
            return super().check(key)
        now = time.time()
        store_key = f"{self.__prefix}:{key}"
        raw = self.__store.get(store_key)
        last: float = raw if isinstance(raw, (int, float)) else 0.0
        if now - last < self._interval / self._max_rate:
            return False
        self.__store.set(store_key, now)
        return True


class IdempotencyGuard:
    """Prevents duplicate event processing by tracking seen event IDs per handler.
    
    Bounded per-handler to prevent unbounded memory growth.
    """

    def __init__(self, max_ids_per_handler: int = 100000) -> None:
        """Initialises an empty idempotency guard.

        Args:
            max_ids_per_handler: Maximum event IDs tracked per handler
                before oldest entries are evicted.
        """
        self.__lock: threading.Lock = threading.Lock()
        self.__seen: dict[str, set[str]] = {}
        self.__order: dict[str, list[str]] = {}
        self.__max_ids: int = max_ids_per_handler

    @property
    def total_tracked_events(self) -> int:
        """Returns the total number of event IDs tracked across all handlers."""
        with self.__lock:
            return sum(len(ids) for ids in self.__seen.values())

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
            order = self.__order.setdefault(handler_id, [])
            if event_id in seen:
                return True
            seen.add(event_id)
            order.append(event_id)
            if len(seen) > self.__max_ids:
                evicted = order.pop(0)
                seen.discard(evicted)
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

    def __init__(self,
                 rate_limit: float = 0.0,
                 max_workers: int = 0,
                 max_futures: int = 10000,
                 max_buffer_size: int = 0,
                 store: Store | None = None) -> None:
        """Initialises the local bus.

        Args:
            rate_limit: Max events per second per subscriber (0 = unlimited).
            max_workers: Thread pool size (0 = synchronous dispatch).
            max_futures: Max pending futures before backpressure.
            max_buffer_size: Max pending events in buffer (0 = unlimited).
            store: Optional Store for DLQ persistence.
        """
        self.__lock: threading.RLock = threading.RLock()
        self.__handlers: dict[str, list[tuple[str, Callable[[Event],
                                                            None]]]] = {}
        self.__buffer: list[Event] = []
        self.__running: bool = False
        self.__dlq: DeadLetterQueue = DeadLetterQueue(store=store)
        self.__idempotency: IdempotencyGuard = IdempotencyGuard()
        self.__circuit_breaker: CircuitBreaker = CircuitBreaker()
        self.__max_buffer_size: int = max_buffer_size
        self.__rate_limiter: RateLimiter | None = RateLimiter(
            rate_limit) if rate_limit > 0 else None
        self.__executor: concurrent.futures.ThreadPoolExecutor | None = (
            concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers) if max_workers > 0 else None)
        self.__futures: list[concurrent.futures.Future] = []
        self.__MAX_FUTURES: int = max_futures

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
            if self.__max_buffer_size > 0 and len(
                    self.__buffer) >= self.__max_buffer_size:
                dropped = self.__buffer.pop(0)
                logger.warning("buffer full, dropping oldest event %s (%s)",
                               dropped.event_id, dropped.event_type)
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
            for f in self.__futures:
                if not f.done():
                    try:
                        f.result(timeout=5)
                    except Exception:
                        logger.debug("future %s timed out on stop", f)
                        logger.debug("future details", exc_info=True)
            self.__executor.shutdown(wait=True)
        self.__futures.clear()

    def __flush(self) -> None:
        pending, self.__buffer = self.__buffer, []
        for event in pending:
            handlers = self.__handlers.get(event.event_type,
                                           []) + self.__handlers.get("*", [])
            for sid, handler in handlers:
                if not self.__circuit_breaker.allow_request(sid):
                    logger.warning(
                        "circuit open for subscriber %s, sending %s to DLQ",
                        sid, event.event_type)
                    self.__dlq.put(event, "circuit_open", sid)
                    continue
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
            self.__circuit_breaker.record_success(sid)
        except Exception as exc:
            logger.warning("subscriber %s failed on %s (%s), sent to DLQ", sid,
                           event.event_type, exc)
            tb = traceback.format_exc()
            self.__dlq.put(event, f"{exc}\n{tb}", sid)
            self.__circuit_breaker.record_failure(sid)

    def __dispatch(self, handler: Callable[[Event], None], event: Event,
                   sid: str) -> None:
        try:
            handler(event)
            self.__circuit_breaker.record_success(sid)
        except Exception as exc:
            logger.warning("subscriber %s failed on %s (%s), sent to DLQ", sid,
                           event.event_type, exc)
            tb = traceback.format_exc()
            self.__dlq.put(event, f"{exc}\n{tb}", sid)
            self.__circuit_breaker.record_failure(sid)


class AsyncEventBus(ABC):
    """Abstract async event bus. Same contract as EventBus but for async subscribers."""

    @abstractmethod
    async def publish(self, event: Event) -> str:
        """Publishes an event to all matching subscribers. Returns the event ID."""

    @abstractmethod
    async def subscribe(self, event_type: str, handler: Callable[[Event],
                                                                 None]) -> str:
        """Registers a handler for *event_type* (use ``*`` for wildcard).

        Returns a subscription ID that can be passed to ``unsubscribe``.
        """

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription."""

    @abstractmethod
    async def start(self) -> None:
        """Starts delivering buffered events."""

    @abstractmethod
    async def stop(self) -> None:
        """Stops event delivery and clears all subscriptions."""

    @property
    @abstractmethod
    def dlq(self) -> DeadLetterQueue:
        """Returns the dead-letter queue for this bus."""

    @property
    @abstractmethod
    def idempotency(self) -> IdempotencyGuard:
        """Returns the idempotency guard for this bus."""


class AsyncLocalBus(AsyncEventBus):
    """Async in-process event bus — uses asyncio for non-blocking dispatch.

    Wraps a synchronous LocalBus and dispatches events in a thread pool
    executor to avoid blocking the async event loop.
    """

    def __init__(self,
                 rate_limit: float = 0.0,
                 max_workers: int = 4,
                 max_futures: int = 10000,
                 store: Store | None = None) -> None:
        self.__loop: asyncio.AbstractEventLoop | None = None
        self.__local_bus: LocalBus = LocalBus(
            rate_limit=rate_limit,
            max_workers=max_workers,
            max_futures=max_futures,
            store=store,
        )
        self.__running: bool = False

    @property
    def dlq(self) -> DeadLetterQueue:
        return self.__local_bus.dlq

    @property
    def idempotency(self) -> IdempotencyGuard:
        return self.__local_bus.idempotency

    async def publish(self, event: Event) -> str:
        self.__local_bus.publish(event)
        return event.event_id

    async def subscribe(self, event_type: str, handler: Callable[[Event],
                                                                 None]) -> str:
        return self.__local_bus.subscribe(event_type, handler)

    async def unsubscribe(self, subscription_id: str) -> None:
        self.__local_bus.unsubscribe(subscription_id)

    async def start(self) -> None:
        self.__running = True
        self.__local_bus.start()

    async def stop(self) -> None:
        self.__running = False
        self.__local_bus.stop()
