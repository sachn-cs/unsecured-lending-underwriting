"""Fraud detection - velocity checks, wash lending, and rule-based alerts."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import StatefulService
from underwrite.services.persistence import BatchedStoreRepository
from underwrite.validate import get_finite, get_non_empty

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer

class FraudHandler(StatefulService):
    """Detects wash lending, burst origination patterns, and configurable fraud rules."""

    MAX_BORROWERS: int = 100000
    SYNC_INTERVAL: int = 10
    LARGE_PRINCIPAL_THRESHOLD: float = 1_000_000.0
    ACTIVITY_DEQUE_MAXLEN: int = 1000
    WASH_SCORE_PER_CYCLE: float = 16.67
    MAX_FRAUD_SCORE: float = 100.0

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the fraud service with an empty activity record store.

        Args:
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(
            service_id=service_id,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__records: dict[str, deque[dict[str, Any]]] = {}
        self.repo: BatchedStoreRepository[dict[str, list[dict[str, Any]]]] = self.batched_repo(
            "records", dict, sync_interval=self.SYNC_INTERVAL
        )

    def start(self) -> None:
        """Load persisted fraud records when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.__records = self.__deserialize_records(loaded)

    @property
    def records(self) -> dict[str, deque[dict[str, Any]]]:
        """Return a snapshot of the internal records dict (test-accessible hook).

        Returns:
            Dict mapping borrower IDs to their activity deques.
        """
        with self.state_lock:
            return {k: deque(v, maxlen=v.maxlen) for k, v in self.__records.items()}

    def handle(self, event: Event) -> None:
        """Check loan origination and repayment events against fraud rules.

        Triggers alerts for wash lending cycles, velocity bursts, and
        large-value originations.

        Args:
            event: The incoming event. LOAN_ORIGINATED and REPAID are processed.
        """
        if event.event_type == EventType.LOAN_ORIGINATED:
            borrower: str = get_non_empty(event.payload, "borrower")
            principal: float = get_finite(event.payload, "principal")
            with self.state_lock:
                self.__record(borrower, "origination", principal)
                self.__check_wash(borrower, event.correlation_id)
                self.__check_burst(borrower, event.correlation_id)
            if principal > self.LARGE_PRINCIPAL_THRESHOLD:
                self.emit(
                    EventType.FRAUD_ALERT,
                    {
                        "rule": "large_origination",
                        "borrower": borrower,
                        "principal": principal,
                    },
                    correlation_id=event.correlation_id,
                )
        elif event.event_type == EventType.REPAID:
            user: str = get_non_empty(event.payload, "user")
            delta: float = get_finite(event.payload, "delta_earned")
            with self.state_lock:
                self.__record(user, "repayment", delta)
                self.__check_wash(user, event.correlation_id)

    def __record(self, borrower: str, event_type: str, amount: float) -> None:
        """Record an activity event for a borrower.

        Args:
            borrower: The borrower identifier.
            event_type: Type of event (origination or repayment).
            amount: Transaction amount.
        """
        if borrower not in self.__records:
            if len(self.__records) >= self.MAX_BORROWERS:
                self.__records.pop(next(iter(self.__records)))
            self.__records[borrower] = deque(maxlen=self.ACTIVITY_DEQUE_MAXLEN)
        else:
            records = self.__records.pop(borrower)
            self.__records[borrower] = records
        records = self.__records[borrower]
        records.append(
            {
                "event_type": event_type,
                "amount": amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.repo.incr_and_maybe_sync(self.__serialize_records())

    def __check_wash(self, borrower: str, correlation_id: str) -> None:
        """Check for wash lending cycles (alternating origination/repayment).

        Args:
            borrower: The borrower identifier.
            correlation_id: Correlation ID for tracing.
        """
        records = self.__records.get(borrower, deque(maxlen=self.ACTIVITY_DEQUE_MAXLEN))
        if len(records) < 2:
            return
        types = {r["event_type"] for r in records}
        if len(types) < 2:
            return
        cycles: int = 0
        i: int = 0
        while i < len(records) - 1:
            if records[i]["event_type"] == "origination" and records[i + 1]["event_type"] == "repayment":
                cycles += 1
                i += 2
            else:
                i += 1
        if cycles >= 3:
            self.emit(
                EventType.WASH_FLAG,
                {
                    "borrower": borrower,
                    "cycles": cycles,
                    "score": min(self.MAX_FRAUD_SCORE, cycles * self.WASH_SCORE_PER_CYCLE),
                },
                correlation_id=correlation_id,
            )

    def __check_burst(self, borrower: str, correlation_id: str) -> None:
        """Check for velocity bursts (multiple rapid originations).

        Args:
            borrower: The borrower identifier.
            correlation_id: Correlation ID for tracing.
        """
        records = self.__records.get(borrower, deque(maxlen=self.ACTIVITY_DEQUE_MAXLEN))
        recent = [r for r in records if r["event_type"] == "origination"]
        if len(recent) > 3:
            self.emit(
                EventType.VELOCITY_FLAG,
                {
                    "borrower": borrower,
                    "count": len(recent),
                },
                correlation_id=correlation_id,
            )

    def __serialize_records(self) -> dict[str, list[dict[str, Any]]]:
        """Convert internal records dict to store-friendly dict of lists.

        Returns:
            Serialized records suitable for storage.
        """
        return {k: list(v) for k, v in self.__records.items()}

    @staticmethod
    def __deserialize_records(
        raw: dict[str, list[dict[str, Any]]],
    ) -> dict[str, deque[dict[str, Any]]]:
        """Restore internal dict of deques from store-friendly dict of lists.

        Args:
            raw: Store-friendly dict of lists.

        Returns:
            Restored dict of deques.
        """
        return {k: deque(v, maxlen=self.ACTIVITY_DEQUE_MAXLEN) for k, v in raw.items() if isinstance(v, list)}
