# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Async-native event bus — ``asyncio.Queue``-based ``AsyncEventBus``.

Provides a non-blocking, async-first alternative to the synchronous
``EventBus`` for high-throughput event pipelines where handlers should
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

from underwrite.bus import AsyncEventBus, Guard, Message, Queue
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
        self.async_queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)
        self.async_subscribers: dict[str, list[Callable[[Message], Any]]] = {}
        self.async_subscription_ids: dict[str, tuple[str, Callable[[Message], Any]]] = {}
        self.async_subscription_lock: asyncio.Lock = asyncio.Lock()
        self.async_task: asyncio.Task[None] | None = None
        self.async_running: bool = False
        self.async_stop_event: asyncio.Event = asyncio.Event()
        self.async_semaphore: asyncio.Semaphore | None = asyncio.Semaphore(max_workers) if max_workers > 0 else None
        self.bus_dlq: Queue = Queue(store=store)
        self.bus_idempotency: Guard = Guard()
        self.async_handler_timeout: float = handler_timeout

    @property
    def dlq(self) -> Queue:
        return self.bus_dlq

    @property
    def idempotency(self) -> Guard:
        return self.bus_idempotency

    def is_stopped(self) -> bool:
        return not self.async_running

    async def start(self) -> None:
        if self.async_running:
            return
        self.async_running = True
        self.async_stop_event.clear()
        self.async_task = asyncio.create_task(self.async_dispatch_loop())
        logger.info("AsyncEventBus started")

    async def stop(self) -> None:
        self.async_running = False
        self.async_stop_event.set()
        # Drain any remaining events from the queue
        drained = 0
        while not self.async_queue.empty():
            try:
                event = self.async_queue.get_nowait()
                await self.dispatch(event)
                drained += 1
            except asyncio.QueueEmpty:
                break
        if self.async_task is not None:
            self.async_task.cancel()
            try:
                await self.async_task
            except asyncio.CancelledError:
                pass
            self.async_task = None
        logger.info("AsyncEventBus stopped (drained {} events)", drained)

    async def publish(self, event: Message) -> str:
        await self.async_queue.put(event)
        return event.event_id

    async def subscribe(self, event_type: str, handler: Callable[[Message], Any]) -> str:
        sid = str(uuid.uuid4())
        async with self.async_subscription_lock:
            self.async_subscribers.setdefault(event_type, []).append(handler)
            self.async_subscription_ids[sid] = (event_type, handler)
        return sid

    async def unsubscribe(self, subscription_id: str) -> None:
        async with self.async_subscription_lock:
            meta = self.async_subscription_ids.pop(subscription_id, None)
            if meta is not None:
                event_type, handler = meta
                handlers = self.async_subscribers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)

    async def async_dispatch_loop(self) -> None:
        while self.async_running:
            getter = asyncio.create_task(self.async_queue.get())
            stopper = asyncio.create_task(self.async_stop_event.wait())
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
            event: Message = getter.result()
            try:
                await self.dispatch(event)
            except asyncio.CancelledError:
                break
            except (RuntimeError, ValueError, TypeError, OSError, AttributeError, KeyError):
                logger.exception("dispatch loop: unexpected error processing {}", event.event_id)

    async def dispatch(self, event: Message) -> None:
        async with self.async_subscription_lock:
            handlers = list(self.async_subscribers.get(event.event_type, []))
            wild_handlers = list(self.async_subscribers.get("*", []))
        handlers = handlers + wild_handlers
        if not handlers:
            return
        if self.async_semaphore is not None:

            async def bounded(h, e):
                async with self.async_semaphore:
                    await self.safe_dispatch(h, e)

            coros = [__bounded(h, event) for h in handlers]
        else:
            coros = [self.safe_dispatch(h, event) for h in handlers]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=self.async_handler_timeout * 2,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "aggregate dispatch timeout after {:.1f}s for event {}; cancelling pending handlers",
                self.async_handler_timeout * 2,
                event.event_id,
            )
            return
        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("async handler {} failed: {}", getattr(handler, "__name__", str(handler)), result)

    async def safe_dispatch(self, handler: Callable[[Message], Any], event: Message) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=self.async_handler_timeout)
        except asyncio.TimeoutError:
            msg = f"handler timed out after {self.async_handler_timeout}s"
            logger.warning("async handler timed out for {}: {}", event.event_id, handler.__name__)
            self.bus_dlq.put(event, msg, handler.__name__)
        except Exception as exc:
            logger.exception("async handler failed for {}", event.event_id)
            self.bus_dlq.put(event, f"{type(exc).__name__}: {exc}", handler.__name__)
