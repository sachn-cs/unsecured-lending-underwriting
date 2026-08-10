"""Async-native event bus — ``asyncio.Queue``-based ``AsyncEventBus``.

Provides a non-blocking, async-first alternative to the synchronous
``LocalBus`` for high-throughput event pipelines where handlers should
not block publishers.
"""

from __future__ import annotations

__all__ = [
    "AsyncLocalBus",
]

import asyncio
import inspect
import uuid
from collections.abc import Callable
from typing import Any

from underwrite.bus import AsyncEventBus, Event, Guard, Queue
from underwrite.logger import logger
from underwrite.store import Store

HANDLER_TIMEOUT: float = 30.0  # max seconds per async handler


class AsyncLocalBus(AsyncEventBus):
    """asyncio-based event bus with an internal ``asyncio.Queue``.

    ``publish()`` enqueues events; a background ``asyncio.Task`` dequeues
    and dispatches them to subscribed handlers concurrently via
    ``asyncio.gather()``.

    Each handler has a per-execution timeout (*HANDLER_TIMEOUT*) to
    prevent a single slow handler from blocking the dispatch group.
    The dispatch loop blocks on the queue with an ``asyncio.Event``
    for shutdown signalling, so it does not waste CPU on a
    timeout-based wakeup.
    """

    def __init__(
        self,
        maxsize: int = 0,
        max_workers: int = 0,
        store: Store | None = None,
        handler_timeout: float = HANDLER_TIMEOUT,
    ) -> None:
        self.__queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.__subscribers: dict[str, list[Callable[[Event], Any]]] = {}
        self.__subscription_ids: dict[str, tuple[str, Callable[[Event], Any]]] = {}
        self.__subscription_lock: asyncio.Lock = asyncio.Lock()
        self.__task: asyncio.Task[None] | None = None
        self.__running: bool = False
        self.__stop_event: asyncio.Event = asyncio.Event()
        self.__semaphore: asyncio.Semaphore | None = asyncio.Semaphore(max_workers) if max_workers > 0 else None
        self.__dlq: Queue = Queue(store=store)
        self.__idempotency: Guard = Guard()
        self.__handler_timeout: float = handler_timeout

    @property
    def dlq(self) -> Queue:
        return self.__dlq

    @property
    def idempotency(self) -> Guard:
        return self.__idempotency

    def is_stopped(self) -> bool:
        return not self.__running

    async def start(self) -> None:
        if self.__running:
            return
        self.__running = True
        self.__stop_event.clear()
        self.__task = asyncio.create_task(self.__dispatch_loop())
        logger.info("AsyncLocalBus started")

    async def stop(self) -> None:
        self.__running = False
        self.__stop_event.set()
        # Drain any remaining events from the queue
        drained = 0
        while not self.__queue.empty():
            try:
                event = self.__queue.get_nowait()
                await self.__dispatch(event)
                drained += 1
            except asyncio.QueueEmpty:
                break
        if self.__task is not None:
            self.__task.cancel()
            try:
                await self.__task
            except asyncio.CancelledError:
                pass
            self.__task = None
        logger.info("AsyncLocalBus stopped (drained {} events)", drained)

    async def publish(self, event: Event) -> str:
        await self.__queue.put(event)
        return event.event_id

    async def subscribe(self, event_type: str, handler: Callable[[Event], Any]) -> str:
        sid = str(uuid.uuid4())
        async with self.__subscription_lock:
            self.__subscribers.setdefault(event_type, []).append(handler)
            self.__subscription_ids[sid] = (event_type, handler)
        return sid

    async def unsubscribe(self, subscription_id: str) -> None:
        async with self.__subscription_lock:
            meta = self.__subscription_ids.pop(subscription_id, None)
            if meta is not None:
                event_type, handler = meta
                handlers = self.__subscribers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)

    async def __dispatch_loop(self) -> None:
        while self.__running:
            getter = asyncio.create_task(self.__queue.get())
            stopper = asyncio.create_task(self.__stop_event.wait())
            try:
                done, pending = await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                getter.cancel()
                stopper.cancel()
                raise
            for p in pending:
                p.cancel()
            if stopper in done:
                getter.cancel()
                break
            event: Event = getter.result()
            try:
                await self.__dispatch(event)
            except asyncio.CancelledError:
                break
            except (RuntimeError, ValueError, TypeError, OSError, AttributeError, KeyError):
                logger.exception("dispatch loop: unexpected error processing {}", event.event_id)

    async def __dispatch(self, event: Event) -> None:
        async with self.__subscription_lock:
            handlers = list(self.__subscribers.get(event.event_type, []))
            wild_handlers = list(self.__subscribers.get("*", []))
        handlers = handlers + wild_handlers
        if not handlers:
            return
        if self.__semaphore is not None:

            async def __bounded(h, e):
                async with self.__semaphore:
                    await self.__safe_dispatch(h, e)

            coros = [__bounded(h, event) for h in handlers]
        else:
            coros = [self.__safe_dispatch(h, event) for h in handlers]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=self.__handler_timeout * 2,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "aggregate dispatch timeout after {:.1f}s for event {}; cancelling pending handlers",
                self.__handler_timeout * 2,
                event.event_id,
            )
            return
        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("async handler {} failed: {}", getattr(handler, "__name__", str(handler)), result)

    async def __safe_dispatch(self, handler: Callable[[Event], Any], event: Event) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=self.__handler_timeout)
        except asyncio.TimeoutError:
            msg = f"handler timed out after {self.__handler_timeout}s"
            logger.warning("async handler timed out for {}: {}", event.event_id, handler.__name__)
            self.__dlq.put(event, msg, handler.__name__)
        except Exception as exc:
            logger.exception("async handler failed for {}", event.event_id)
            self.__dlq.put(event, f"{type(exc).__name__}: {exc}", handler.__name__)
