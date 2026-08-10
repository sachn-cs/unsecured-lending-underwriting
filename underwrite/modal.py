# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Modal-backed event bus implementation.

Publishes events to a Modal distributed queue and polls for messages
in a background thread.  Requires ``modal`` (install ``underwrite[modal]``).
"""

from __future__ import annotations

import importlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from types import ModuleType
from typing import Any

from underwrite.bus import Breaker, EventBus, Guard, Queue
from underwrite.logger import logger
from underwrite.message import Message
from underwrite.store import Store


class ModalBus(EventBus):
    """Message bus backed by a Modal distributed queue."""

    def __init__(
        self,
        queue_name: str = "underwrite-bus",
        poll_interval: float = 1.0,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        store: Store | None = None,
    ) -> None:
        self.__queue_name: str = queue_name
        self.__poll_interval: float = max(0.1, poll_interval)
        self.__modal: ModuleType | None = None
        self.__modal_queue: Any = None
        self.__handlers: dict[str, list[tuple[str, Callable[[Message], None]]]] = {}
        self.__running: bool = False
        self.__poll_thread: threading.Thread | None = None
        self.__lock: threading.Lock = threading.Lock()
        self.__dlq: Queue = Queue(store=store)
        self.__idempotency: Guard = Guard()
        self.__circuit_breaker: Breaker = Breaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
        self.__import_modal()

    def __import_modal(self) -> None:
        try:
            self.__modal = importlib.import_module("modal")
            self.__modal_queue = self.__modal.Queue(self.__queue_name)
        except ImportError:
            self.__modal = None

    def publish(self, event: Message) -> str:
        if self.__modal is None:
            raise RuntimeError("modal is not installed; install underwrite[modal]")
        if self.__modal_queue is None:
            raise RuntimeError("modal queue is not initialized")
        body: str = json.dumps(event.to_dict())
        self.__modal_queue.put(body)
        return event.event_id

    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str:
        sid: str = uuid.uuid4().hex
        with self.__lock:
            self.__handlers.setdefault(event_type, []).append((sid, handler))
        return sid

    def unsubscribe(self, subscription_id: str) -> None:
        with self.__lock:
            for handlers in self.__handlers.values():
                idx = next((i for i, (sid, _) in enumerate(handlers) if sid == subscription_id), None)
                if idx is not None:
                    handlers.pop(idx)
                    return

    def start(self) -> None:
        if self.__running:
            return
        self.__running = True
        self.__poll_thread = threading.Thread(target=self.__poll_loop, daemon=True, name="modal-poll")
        self.__poll_thread.start()

    def stop(self) -> None:
        self.__running = False
        if self.__poll_thread:
            self.__poll_thread.join(timeout=5)
            self.__poll_thread = None
        with self.__lock:
            self.__handlers.clear()

    @property
    def dlq(self) -> Queue:
        return self.__dlq

    @property
    def idempotency(self) -> Guard:
        return self.__idempotency

    def __poll_loop(self) -> None:
        while self.__running:
            try:
                if self.__modal_queue is None:
                    time.sleep(self.__poll_interval)
                    continue
                time.sleep(self.__poll_interval)
                if not self.__running:
                    break
                raw = self.__modal_queue.get(block=False)
                while raw is not None and self.__running:
                    data: dict[str, Any] = json.loads(raw)
                    event: Message = Message.from_dict(data)
                    self.__dispatch(event)
                    raw = self.__modal_queue.get(block=False)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("modal poll message parse error: {}", exc)
            except Exception as exc:
                if self.__running:
                    logger.warning("modal poll error: {}", exc)

    def __dispatch(self, event: Message) -> None:
        with self.__lock:
            wildcards: list[tuple[str, Callable[[Message], None]]] = self.__handlers.get("*", [])
            specific: list[tuple[str, Callable[[Message], None]]] = self.__handlers.get(event.event_type, [])
        for sid, handler in wildcards + specific:
            if not self.__circuit_breaker.allow_request(sid):
                logger.warning("circuit open for subscriber {}, sending {} to DLQ", sid, event.event_type)
                self.__dlq.put(event, "circuit_open", sid)
                continue
            try:
                handler(event)
                self.__circuit_breaker.record_success(sid)
            except Exception as exc:
                logger.exception("handler failed for {}", event.event_type)
                self.__dlq.put(event, f"{type(exc).__name__}: {exc}", sid)
                self.__circuit_breaker.record_failure(sid)
