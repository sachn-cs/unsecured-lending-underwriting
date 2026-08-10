# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Service supervisor — monitors and auto-restarts crashed services.

Tracks consecutive failures per service.  If a service exceeds the
max restart threshold it is permanently marked unhealthy.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from underwrite.logger import logger


class Watcher:
    """Monitors service health and auto-restarts crashed services."""

    def __init__(self, max_restarts: int = 3, backoff_seconds: float = 1.0, cooldown_seconds: float = 30.0) -> None:
        self.max_restarts_limit: int = max_restarts
        self.backoff_base: float = backoff_seconds
        self.cooldown_seconds: float = cooldown_seconds
        self.supervisor_lock: threading.RLock = threading.RLock()
        self.failure_counts: dict[str, int] = {}
        self.last_restart_times: dict[str, float] = {}

    def record_failure(self, service_id: str) -> bool:
        """Records a handler failure. Returns True if restart is allowed."""
        with self.supervisor_lock:
            count = self.failure_counts.get(service_id, 0) + 1
            self.failure_counts[service_id] = count
            if count > self.max_restarts_limit:
                logger.error("service {} exceeded max restarts ({}); giving up", service_id, self.max_restarts_limit)
                return False
            logger.warning("service {} failure {}/{}; will restart", service_id, count, self.max_restarts_limit)
            return True

    def record_success(self, service_id: str) -> None:
        """Decrements failure count after a successful handler execution (gradual recovery)."""
        with self.supervisor_lock:
            count = self.failure_counts.get(service_id, 0)
            if count > 1:
                self.failure_counts[service_id] = count - 1
            elif count == 1:
                del self.failure_counts[service_id]

    def record_restart(self, service_id: str) -> None:
        """Records the time of a service restart for cooldown enforcement."""
        with self.supervisor_lock:
            self.last_restart_times[service_id] = time.monotonic()

    def reset(self, service_id: str) -> None:
        """Resets the failure count for a service."""
        with self.supervisor_lock:
            self.failure_counts.pop(service_id, None)

    def backoff(self, service_id: str) -> float:
        """Returns the backoff delay in seconds before restarting."""
        with self.supervisor_lock:
            count = self.failure_counts.get(service_id, 0)
            if count <= 0:
                return 0.0
            return min(self.backoff_base * (2.0 ** (count - 1)), 60.0)

    def should_restart(self, service_id: str) -> bool:
        """Returns True if the service should be restarted based on failure count and cooldown."""
        with self.supervisor_lock:
            count = self.failure_counts.get(service_id, 0)
            if count <= 0 or count > self.max_restarts_limit:
                return False
            last = self.last_restart_times.get(service_id, 0.0)
            if time.monotonic() - last < self.cooldown_seconds:
                return False
            return True

    def failing_services(self) -> list[str]:
        """Returns list of service IDs that have recorded failures."""
        with self.supervisor_lock:
            return list(self.failure_counts.keys())

    def health(self) -> dict[str, Any]:
        """Returns health status for all tracked services."""
        with self.supervisor_lock:
            return {
                "ok": all(c <= self.max_restarts_limit for c in self.failure_counts.values()),
                "total_failures": sum(self.failure_counts.values()),
                "restarting": list(self.failure_counts.keys()),
            }

    def shutdown(self) -> None:
        """Clears all tracked failure state during shutdown."""
        with self.supervisor_lock:
            self.failure_counts.clear()


__all__ = ["Watcher"]
