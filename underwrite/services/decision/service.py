"""Decision intelligence service.

Aggregates signals from fraud, risk, and compliance services to produce
a consolidated decision recommendation.  Emits ``decision.made`` with
the recommended action and supporting evidence.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.base import NanoService


class DecisionService(NanoService):
    """Consolidates multi-signal inputs into a single decision recommendation.

    Collects fraud alerts, risk scores, and compliance outcomes to
    recommend an action: approve, reject, review, or escalate.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__lock: threading.Lock = threading.Lock()
        self.__signals: dict[str, list[dict[str, Any]]] = {}

    def handle(self, event: Event) -> None:
        entity_id: str = event.payload.get(
            "application_id", "") or event.payload.get("loan_id", "")
        if not entity_id:
            return

        if event.event_type == EventType.FRAUD_ALERT:
            with self.__lock:
                self.__signals.setdefault(entity_id, []).append({
                    "source": "fraud",
                    "type": "alert",
                    "severity": event.payload.get("severity", "high"),
                    "detail": event.payload.get("reason", ""),
                })

        elif event.event_type == EventType.RISK_SCORED:
            score: float = float(event.payload.get("score", 0))
            signal: dict[str, Any] = {
                "source": "risk",
                "type": "score",
                "value": score,
            }
            if score >= 0.7:
                signal["severity"] = "high"
            elif score >= 0.4:
                signal["severity"] = "medium"
            else:
                signal["severity"] = "low"
            with self.__lock:
                self.__signals.setdefault(entity_id, []).append(signal)

        elif event.event_type == "decision.evaluate":
            with self.__lock:
                signals = self.__signals.pop(entity_id, [])
            high_signals: int = sum(
                1 for s in signals if s.get("severity") == "high")
            medium_signals: int = sum(
                1 for s in signals if s.get("severity") == "medium")

            if high_signals > 0:
                action: str = "reject"
            elif medium_signals > 2:
                action = "escalate"
            elif medium_signals > 0:
                action = "review"
            else:
                action = "approve"

            self.store.set(
                f"decision:{entity_id}", {
                    "entity_id": entity_id,
                    "action": action,
                    "signals": signals,
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                })
            self.emit(EventType.DECISION_MADE, {
                "entity_id": entity_id,
                "action": action,
                "signal_count": len(signals),
            },
                      correlation_id=event.correlation_id)
