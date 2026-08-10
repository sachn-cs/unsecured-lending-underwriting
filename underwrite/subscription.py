"""Subscription registry + async dispatcher."""

from __future__ import annotations

import concurrent.futures
import threading
import uuid
from collections.abc import Callable
from typing import Any

from underwrite.logger import logger
from underwrite.message import Message


class Registry:
    """Tracks (subscription_id, handler) tuples keyed by event type.

    Pulled out of EventBus so the bus is not responsible for both
    managing subscribers and dispatching events.
    """

    def __init__(self) -> None:
        self.__lock: threading.RLock = threading.RLock()
        self.__handlers: dict[str, list[tuple[str, Callable[[Message], None]]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str:
        """Register a handler for a given event type.

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
        """Remove a previously registered subscription.

        Args:
            subscription_id: The ID returned by ``subscribe``.
        """
        with self.__lock:
            for event_type in list(self.__handlers):
                self.__handlers[event_type] = [
                    (sid, h) for sid, h in self.__handlers[event_type] if sid != subscription_id
                ]

    def handlers_for(self, event_type: str) -> list[tuple[str, Callable[[Message], None]]]:
        """Return a snapshot of (sid, handler) tuples for the given event type.

        Combines the specific-type bucket with the wildcard (``"*"``) bucket.
        """
        with self.__lock:
            return list(self.__handlers.get(event_type, [])) + list(self.__handlers.get("*", []))

    def count(self, event_type: str | None = None) -> int:
        """Return the number of registered subscribers.

        Args:
            event_type: If provided, count only subscribers to that event type;
                pass ``"*"`` for the wildcard bucket, or ``None`` for the total.
        """
        with self.__lock:
            if event_type is None:
                return sum(len(handlers) for handlers in self.__handlers.values())
            return len(self.__handlers.get(event_type, ()))

    def clear(self) -> None:
        """Remove all subscriptions."""
        with self.__lock:
            self.__handlers.clear()


class Dispatcher:
    """Owns the thread-pool executor and pending-future bookkeeping for async dispatch.

    Pulled out of EventBus so the bus is not responsible for both
    subscriber bookkeeping and async-executor lifecycle. Provides
    submit-and-trim, future-completion observation, and graceful
    shutdown of the underlying executor.
    """

    def __init__(self, max_workers: int, max_futures: int) -> None:
        self.__executor: concurrent.futures.ThreadPoolExecutor | None = (
            concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) if max_workers > 0 else None
        )
        self.__futures: list[concurrent.futures.Future] = []
        self.__MAX_FUTURES: int = max_futures

    def submit(self, fn: Callable[..., Any], *args: Any) -> concurrent.futures.Future | None:
        """Submit work to the executor pool.

        Returns:
            The submitted Future, or None if no executor was configured.
        """
        if self.__executor is None:
            return None
        future = self.__executor.submit(fn, *args)
        future.add_done_callback(self.__handle_future)
        self.__futures.append(future)
        self.__trim_futures()
        return future

    def has_executor(self) -> bool:
        return self.__executor is not None

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        """Wait for outstanding futures and shut the executor down."""
        if self.__executor is not None:
            done, not_done = concurrent.futures.wait(
                self.__futures, timeout=timeout_seconds, return_when=concurrent.futures.ALL_COMPLETED
            )
            if not_done:
                logger.warning("{} future(s) did not complete within stop timeout", len(not_done))
            self.__executor.shutdown(wait=True)
        self.__futures.clear()

    def __handle_future(self, f: concurrent.futures.Future) -> None:
        try:
            exc = f.exception(timeout=0)
        except concurrent.futures.TimeoutError:
            return
        if exc is not None:
            logger.warning("future {} raised: {}", f, exc)

    def __trim_futures(self) -> None:
        if len(self.__futures) < self.__MAX_FUTURES:
            return
        done = [f for f in self.__futures if f.done()]
        for f in done:
            try:
                exc = f.exception(timeout=0)
            except concurrent.futures.TimeoutError:
                continue
            if exc is not None:
                logger.warning("future {} raised: {}", f, exc)
        self.__futures = [f for f in self.__futures if not f.done()]
