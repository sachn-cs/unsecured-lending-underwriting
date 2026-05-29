"""RBI regulatory reporting — generates reports from audit data."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite


class ReportingService(NanoService):
    """Generates regulatory reports (RBI, internal) from the audit trail."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__originations: int = 0
        self.__defaults: int = 0
        self.__total_principal: float = 0.0
        self.__load_store()

    def handle(self, event: Event) -> None:
        if event.event_type == EventType.LOAN_ORIGINATED:
            with self.__lock:
                self.__originations += 1
                self.__total_principal += get_finite(event.payload, "principal")
                self.__sync_store()
        elif event.event_type == EventType.DEFAULT_OCCURRED:
            with self.__lock:
                self.__defaults += 1
                self.__sync_store()

    def generate_report(self,
                        report_type: str = "portfolio_summary"
                       ) -> dict[str, Any]:
        """Generate a regulatory report from accumulated metrics.

        Args:
            report_type: Type of report (default "portfolio_summary").

        Returns:
            Dict with report_type, generated_at, total_originations,
            total_defaults, total_principal_originated, and default_rate.
        """
        return {
            "report_type": report_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_originations": self.__originations,
            "total_defaults": self.__defaults,
            "total_principal_originated": self.__total_principal,
            "default_rate": self.__defaults / max(self.__originations, 1),
        }

    # -- state persistence ---------------------------------------------------

    def __sync_store(self) -> None:
        """Persist the in-memory counters to the shared store."""
        with self.__lock:
            self.store.set(
                f"{self.service_id}:counters", {
                    "originations": self.__originations,
                    "defaults": self.__defaults,
                    "total_principal": self.__total_principal,
                })

    def __load_store(self) -> None:
        """Restore the counters from the shared store on startup."""
        raw = self.store.get(f"{self.service_id}:counters")
        if raw is None or not isinstance(raw, dict):
            return
        self.__originations = raw.get("originations", 0)
        self.__defaults = raw.get("defaults", 0)
        self.__total_principal = raw.get("total_principal", 0.0)
