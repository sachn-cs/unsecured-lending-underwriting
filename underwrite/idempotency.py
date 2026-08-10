# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Bounded idempotency guard."""

from __future__ import annotations

import threading
from collections import deque

from underwrite.logger import logger


class Guard:
    """Prevents duplicate event processing by tracking seen event IDs per handler.

    Bounded both per-handler (oldest entry evicted past
    ``max_ids_per_handler``) and globally (oldest handler bucket
    evicted past ``max_handlers``) to prevent unbounded memory
    growth in long-running processes.
    """

    def __init__(self, max_ids_per_handler: int = 100000, max_handlers: int = 1000) -> None:
        """Initializes an empty idempotency guard.

        Args:
            max_ids_per_handler: Maximum event IDs tracked per handler
                before oldest entries are evicted.
            max_handlers: Maximum number of distinct handler ids tracked
                before the oldest handler bucket is evicted.
        """
        self.__lock: threading.Lock = threading.Lock()
        self.__seen: dict[str, set[str]] = {}
        self.__order: dict[str, deque[str]] = {}
        self.__handler_order: deque[str] = deque()
        self.__max_ids: int = max_ids_per_handler
        self.__max_handlers: int = max_handlers

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
            seen = self.__seen.get(handler_id)
            if seen is None:
                seen = set()
                self.__seen[handler_id] = seen
                self.__order[handler_id] = deque()
                self.__handler_order.append(handler_id)
                if len(self.__handler_order) > self.__max_handlers:
                    evicted_handler = self.__handler_order.popleft()
                    self.__seen.pop(evicted_handler, None)
                    self.__order.pop(evicted_handler, None)
                    logger.warning("idempotency guard evicting oldest handler bucket {}", evicted_handler)
            order = self.__order[handler_id]
            if event_id in seen:
                return True
            seen.add(event_id)
            order.append(event_id)
            if len(seen) > self.__max_ids:
                evicted = order.popleft()
                seen.discard(evicted)
                logger.warning("idempotency guard evicting oldest entry for {}", handler_id)
            return False
