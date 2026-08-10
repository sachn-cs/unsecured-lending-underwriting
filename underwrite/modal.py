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
        self.queue_name: str = queue_name
        self.poll_interval: float = max(0.1, poll_interval)
        self.modal: ModuleType | None = None
        self.modal_queue: Any = None
        self.handlers: dict[str, list[tuple[str, Callable[[Message], None]]]] = {}
        self.running: bool = False
        self.poll_thread: threading.Thread | None = None
        self.lock: threading.Lock = threading.Lock()
        self.dlq: Queue = Queue(store=store)
        self.idempotency: Guard = Guard()
        self.circuit_breaker: Breaker = Breaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
        self.import_modal()

    def import_modal(self) -> None:
        try:
            self.modal = importlib.import_module("modal")
            self.modal_queue = self.modal.Queue(self.queue_name)
        except ImportError:
            self.modal = None

    def publish(self, event: Message) -> str:
        if self.modal is None:
            raise RuntimeError("modal is not installed; install underwrite[modal]")
        if self.modal_queue is None:
            raise RuntimeError("modal queue is not initialized")
        body: str = json.dumps(event.to_dict())
        self.modal_queue.put(body)
        return event.event_id

    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str:
        sid: str = uuid.uuid4().hex
        with self.lock:
            self.handlers.setdefault(event_type, []).append((sid, handler))
        return sid

    def unsubscribe(self, subscription_id: str) -> None:
        with self.lock:
            for handlers in self.handlers.values():
                idx = next((i for i, (sid, _) in enumerate(handlers) if sid == subscription_id), None)
                if idx is not None:
                    handlers.pop(idx)
                    return

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.poll_thread = threading.Thread(target=self.poll_loop, daemon=True, name="modal-poll")
        self.poll_thread.start()

    def stop(self) -> None:
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=5)
            self.poll_thread = None
        with self.lock:
            self.handlers.clear()



    def poll_loop(self) -> None:
        while self.running:
            try:
                if self.modal_queue is None:
                    time.sleep(self.poll_interval)
                    continue
                time.sleep(self.poll_interval)
                if not self.running:
                    break
                raw = self.modal_queue.get(block=False)
                while raw is not None and self.running:
                    data: dict[str, Any] = json.loads(raw)
                    event: Message = Message.from_dict(data)
                    self.dispatch(event)
                    raw = self.modal_queue.get(block=False)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("modal poll message parse error: {}", exc)
            except Exception as exc:
                if self.running:
                    logger.warning("modal poll error: {}", exc)

    def dispatch(self, event: Message) -> None:
        with self.lock:
            wildcards: list[tuple[str, Callable[[Message], None]]] = self.handlers.get("*", [])
            specific: list[tuple[str, Callable[[Message], None]]] = self.handlers.get(event.event_type, [])
        for sid, handler in wildcards + specific:
            if not self.circuit_breaker.allow_request(sid):
                logger.warning("circuit open for subscriber {}, sending {} to DLQ", sid, event.event_type)
                self.dlq.put(event, "circuit_open", sid)
                continue
            try:
                handler(event)
                self.circuit_breaker.record_success(sid)
            except Exception as exc:
                logger.exception("handler failed for {}", event.event_type)
                self.dlq.put(event, f"{type(exc).__name__}: {exc}", sid)
                self.circuit_breaker.record_failure(sid)
