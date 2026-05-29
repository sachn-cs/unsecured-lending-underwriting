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
import logging
import uuid
from collections.abc import Callable
from typing import Any

from underwrite.__bus__ import AsyncEventBus, DeadLetterQueue, Event, IdempotencyGuard

logger = logging.getLogger(__name__)


class AsyncLocalBus(AsyncEventBus):
    """asyncio-based event bus with an internal ``asyncio.Queue``.

    ``publish()`` enqueues events; a background ``asyncio.Task`` dequeues
    and dispatches them to subscribed handlers concurrently via
    ``asyncio.gather()``.
    """

    def __init__(
        self,
        maxsize: int = 0,
        max_workers: int = 0,
    ) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._subscribers: dict[str, list[Callable[[Event], Any]]] = {}
        self._subscription_ids: dict[str, tuple[str, Callable[[Event],
                                                              Any]]] = {}
        self._subscription_lock: asyncio.Lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(max_workers) if max_workers > 0 else None)
        self._dlq: DeadLetterQueue = DeadLetterQueue()
        self._idempotency: IdempotencyGuard = IdempotencyGuard()

    @property
    def dlq(self) -> DeadLetterQueue:
        return self._dlq

    @property
    def idempotency(self) -> IdempotencyGuard:
        return self._idempotency

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._dispatch_loop())
        logger.info("AsyncLocalBus started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AsyncLocalBus stopped")

    async def publish(self, event: Event) -> str:
        await self._queue.put(event)
        return event.event_id

    async def subscribe(self, event_type: str, handler: Callable[[Event],
                                                                 Any]) -> str:
        sid = str(uuid.uuid4())
        async with self._subscription_lock:
            self._subscribers.setdefault(event_type, []).append(handler)
            self._subscription_ids[sid] = (event_type, handler)
        return sid

    async def unsubscribe(self, subscription_id: str) -> None:
        async with self._subscription_lock:
            meta = self._subscription_ids.pop(subscription_id, None)
            if meta is not None:
                event_type, handler = meta
                handlers = self._subscribers.get(event_type, [])
                if handler in handlers:
                    handlers.remove(handler)

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            await self._dispatch(event)

    async def _dispatch(self, event: Event) -> None:
        handlers = list(self._subscribers.get(event.event_type, []))
        if not handlers:
            return
        coros = [self._safe_dispatch(h, event) for h in handlers]
        if self._semaphore is not None:

            async def _bounded(h, e):
                async with self._semaphore:
                    await self._safe_dispatch(h, e)

            coros = [_bounded(h, event) for h in handlers]
        await asyncio.gather(*coros, return_exceptions=True)

    @staticmethod
    async def _safe_dispatch(handler: Callable[[Event], Any],
                             event: Event) -> None:
        try:
            result = handler(event)
            if result is not None and hasattr(result, "__await__"):
                await result
        except Exception:
            logger.exception("async handler failed for %s", event.event_id)
