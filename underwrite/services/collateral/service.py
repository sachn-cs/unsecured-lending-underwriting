"""Collateral management — LTV tracking, marking, and liquidation."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty

logger = logging.getLogger(__name__)


class CollateralService(NanoService):
    """Tracks posted collateral against active loans and triggers liquidation on default."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.RLock = threading.RLock()
        self.__ltv_ratio: float = 0.75
        self.__collateral: dict[str, dict[str, Any]] = {}
        self.__load_store()

    def handle(self, event: Event) -> None:
        if event.event_type == EventType.LOAN_ORIGINATED:
            borrower: str = get_non_empty(event.payload, "borrower")
            principal: float = get_finite(event.payload, "principal")
            required: float = principal * self.__ltv_ratio
            with self.__lock:
                self.__collateral[borrower] = {
                    "principal": principal,
                    "required": required,
                    "posted": 0.0,
                    "ltv": self.__ltv_ratio,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self.__sync_store()
            self.emit(EventType.COLLATERAL_MARKED, {
                "borrower": borrower,
                "required": required,
                "ltv_ratio": self.__ltv_ratio,
            },
                      correlation_id=event.correlation_id)
        elif event.event_type == EventType.DEFAULT_OCCURRED:
            borrower = event.payload.get("borrower", "")
            if not borrower:
                logger.warning(
                    "dropping DEFAULT_OCCURRED with missing borrower")
                return
            with self.__lock:
                col = self.__collateral.pop(borrower, None)
                if col:
                    try:
                        self.__sync_store()
                    except Exception:
                        logger.exception(
                            "failed to persist collateral removal for %s, "
                            "restoring in-memory state",
                            borrower,
                        )
                        self.__collateral[borrower] = col
                        raise
            if col:
                self.emit(EventType.COLLATERAL_LIQUIDATED, {
                    "borrower": borrower,
                    "principal": col["principal"],
                    "required": col["required"],
                },
                          correlation_id=event.correlation_id)

    def get(self, borrower: str) -> dict[str, Any] | None:
        """Retrieve collateral record for a borrower.

        Args:
            borrower: The borrower identifier.

        Returns:
            Collateral record dict or None if not found.
        """
        with self.__lock:
            return self.__collateral.get(borrower)

    # -- state persistence ---------------------------------------------------

    def __sync_store(self) -> None:
        """Persist the in-memory collateral to the shared store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:collateral",
                           dict(self.__collateral))

    def __load_store(self) -> None:
        """Restore the collateral from the shared store on startup."""
        raw = self.store.get(f"{self.service_id}:collateral")
        if raw is None or not isinstance(raw, dict):
            return
        self.__collateral = dict(raw)
