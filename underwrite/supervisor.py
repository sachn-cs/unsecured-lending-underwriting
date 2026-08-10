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
        self.__max_restarts: int = max_restarts
        self.__backoff: float = backoff_seconds
        self.__cooldown: float = cooldown_seconds
        self.__lock: threading.RLock = threading.RLock()
        self.__failures: dict[str, int] = {}
        self.__last_restart_time: dict[str, float] = {}

    def record_failure(self, service_id: str) -> bool:
        """Records a handler failure. Returns True if restart is allowed."""
        with self.__lock:
            count = self.__failures.get(service_id, 0) + 1
            self.__failures[service_id] = count
            if count > self.__max_restarts:
                logger.error("service {} exceeded max restarts ({}); giving up", service_id, self.__max_restarts)
                return False
            logger.warning("service {} failure {}/{}; will restart", service_id, count, self.__max_restarts)
            return True

    def record_success(self, service_id: str) -> None:
        """Decrements failure count after a successful handler execution (gradual recovery)."""
        with self.__lock:
            count = self.__failures.get(service_id, 0)
            if count > 1:
                self.__failures[service_id] = count - 1
            elif count == 1:
                del self.__failures[service_id]

    def record_restart(self, service_id: str) -> None:
        """Records the time of a service restart for cooldown enforcement."""
        with self.__lock:
            self.__last_restart_time[service_id] = time.monotonic()

    def reset(self, service_id: str) -> None:
        """Resets the failure count for a service."""
        with self.__lock:
            self.__failures.pop(service_id, None)

    def backoff(self, service_id: str) -> float:
        """Returns the backoff delay in seconds before restarting."""
        with self.__lock:
            count = self.__failures.get(service_id, 0)
            if count <= 0:
                return 0.0
            return min(self.__backoff * (2.0 ** (count - 1)), 60.0)

    def should_restart(self, service_id: str) -> bool:
        """Returns True if the service should be restarted based on failure count and cooldown."""
        with self.__lock:
            count = self.__failures.get(service_id, 0)
            if count <= 0 or count > self.__max_restarts:
                return False
            last = self.__last_restart_time.get(service_id, 0.0)
            if time.monotonic() - last < self.__cooldown:
                return False
            return True

    def failing_services(self) -> list[str]:
        """Returns list of service IDs that have recorded failures."""
        with self.__lock:
            return list(self.__failures.keys())

    def health(self) -> dict[str, Any]:
        """Returns health status for all tracked services."""
        with self.__lock:
            return {
                "ok": all(c <= self.__max_restarts for c in self.__failures.values()),
                "total_failures": sum(self.__failures.values()),
                "restarting": list(self.__failures.keys()),
            }

    def shutdown(self) -> None:
        """Clears all tracked failure state during shutdown."""
        with self.__lock:
            self.__failures.clear()


__all__ = ["Watcher"]
