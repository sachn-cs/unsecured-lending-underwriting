"""Decision intelligence service.

Aggregates signals from fraud, risk, and compliance services to produce
a consolidated decision recommendation. Emits decision.made with the
recommended action and supporting evidence.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator

HIGH_RISK_THRESHOLD: float = 0.7
MEDIUM_RISK_THRESHOLD: float = 0.4


class Handler(StatefulService):
    """Consolidates multi-signal inputs into a single decision recommendation.

    Collects fraud alerts, risk scores, and compliance outcomes to
    recommend an action: approve, reject, review, or escalate.
    """

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
    ) -> None:
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
        self.__clock: SystemClock = SystemClock()
        self.__signals: dict[str, list[dict[str, Any]]] = {}
        self.repo: TypedStoreRepository[dict[str, list[dict[str, Any]]]] = self.store_repo("signals", dict)

    def start(self) -> None:
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.__signals = loaded

    def handle(self, event: Message) -> None:
        """Process signal events and evaluate decisions.

        Args:
            event: The incoming domain event.
        """
        entity_id: str = event.payload.get("application_id", "") or event.payload.get("loan_id", "")
        if not entity_id:
            return

        if event.event_type == Type.FRAUD_ALERT:
            with self.state_lock:
                self.__signals.setdefault(entity_id, []).append(
                    {
                        "source": "fraud",
                        "type": "alert",
                        "severity": event.payload.get("severity", "high"),
                        "detail": event.payload.get("reason", ""),
                    }
                )
                self.repo.save(self.__signals)

        elif event.event_type == Type.RISK_SCORED:
            score: float = PayloadValidator().finite(event.payload, "score", 0.0)
            signal: dict[str, Any] = {
                "source": "risk",
                "type": "score",
                "value": score,
            }
            if score >= HIGH_RISK_THRESHOLD:
                signal["severity"] = "high"
            elif score >= MEDIUM_RISK_THRESHOLD:
                signal["severity"] = "medium"
            else:
                signal["severity"] = "low"
            with self.state_lock:
                self.__signals.setdefault(entity_id, []).append(signal)
                self.repo.save(self.__signals)

        elif event.event_type == Type.DECISION_EVALUATE:
            self.evaluate(entity_id, event.correlation_id)

    def evaluate(self, entity_id: str, correlation_id: str) -> None:
        """Evaluate accumulated signals and emit a decision.

        Args:
            entity_id: The entity identifier to evaluate.
            correlation_id: Correlation ID for tracing.
        """
        with self.state_lock:
            signals = list(self.__signals.get(entity_id, []))
        if not signals:
            return
        high_signals: int = 0
        medium_signals: int = 0
        for s in signals:
            sev = s.get("severity")
            if sev == "high":
                high_signals += 1
            elif sev == "medium":
                medium_signals += 1

        if high_signals > 0:
            action: str = "reject"
        elif medium_signals > 2:
            action = "escalate"
        elif medium_signals > 0:
            action = "review"
        else:
            action = "approve"

        self.store.set(
            f"decision:{entity_id}",
            {
                "entity_id": entity_id,
                "action": action,
                "signals": signals,
                "decided_at": self.__clock.iso(),
            },
        )
        with self.state_lock:
            self.__signals.pop(entity_id, None)
            self.repo.save(self.__signals)
        self.emit(
            Type.DECISION_MADE,
            {
                "entity_id": entity_id,
                "action": action,
                "signal_count": len(signals),
            },
            correlation_id=correlation_id,
        )
