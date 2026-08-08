"""Health check registry for nano-service platform.

Each subsystem registers a callable that returns a dict with at least
``"ok"`` (bool) and optional ``"detail"`` (str).  The registry aggregates
them into a single health report.
"""

from __future__ import annotations

__all__ = [
    "HealthCheck",
    "HealthRegistry",
]

import concurrent.futures
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from underwrite.__logger__ import logger

HealthCheck = Callable[[], dict[str, Any]]


class HealthRegistry:
    """Thread-safe registry of health checks."""

    def __init__(
        self,
        timeout: float = 10.0,
    ) -> None:
        """Initializes an empty health-check registry.

        Args:
            timeout: Max seconds per health check. If a check takes
                longer, it is considered failed (prevents hang-ups).
        """
        self.__lock: threading.Lock = threading.Lock()
        self.__checks: dict[str, HealthCheck] = {}
        self.__timeout: float = timeout
        self.__executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="health",
        )

    def register(self, name: str, check: HealthCheck) -> None:
        """Registers a health check.

        Args:
            name: Unique check name.
            check: Callable returning ``{"ok": bool, ...}``.
        """
        with self.__lock:
            self.__checks[name] = check

    def unregister(self, name: str) -> None:
        """Removes a previously registered health check.

        Args:
            name: The check name to remove.
        """
        with self.__lock:
            self.__checks.pop(name, None)

    def status(self) -> dict[str, Any]:
        """Aggregates all registered health checks into a single report.

        Returns:
            A dict with keys ``"status"`` (``"healthy"`` or ``"degraded"``),
            ``"ok"`` (bool), ``"checks"`` (per-check results), and
            ``"checked_at"`` (ISO-8601 timestamp).
        """
        results: dict[str, Any] = {}
        overall: bool = True
        with self.__lock:
            checks_snapshot = dict(self.__checks)
        for name, check in checks_snapshot.items():
            try:
                fut = self.__executor.submit(check)
                result = fut.result(timeout=self.__timeout)
            except concurrent.futures.TimeoutError:
                logger.warning("health check {} timed out after {:.1f}s", name, self.__timeout)
                result = {
                    "ok": False,
                    "detail": f"timed out after {self.__timeout}s",
                }
            except Exception as exc:
                logger.exception("health check {} failed", name)
                result = {"ok": False, "detail": f"{type(exc).__name__}: {name}"}
            if not result.get("ok", False):
                overall = False
            results[name] = result
        return {
            "status": "healthy" if overall else "degraded",
            "ok": overall,
            "checks": results,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def shutdown(self) -> None:
        """Shuts down the health check thread pool."""
        self.__executor.shutdown(wait=True)
