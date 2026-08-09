"""ML risk scoring and early-warning signals.

Optionally integrates with sklearn-based risk models.  The risk model
path is configurable via the environment or the shared store.
"""

from __future__ import annotations

import os
from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__events__ import Event, EventType
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__logger__ import logger
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.services import Core
from underwrite.services.risk.model import RiskModel
from underwrite.validate import get_finite, get_non_empty


class RiskHandler(Core):
    """Computes default-probability scores and triggers early-warning alerts."""

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
        """Initialise the risk service and optionally load an ML model.

        Args:
            **kwargs: Forwarded to Core.__init__.
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
        self.__model: RiskModel | None = None
        model_path: str = os.environ.get("RISK_MODEL_PATH", "")
        self.__model = RiskModel(model_path) if model_path else RiskModel()

    def set_model(self, model: Any) -> None:
        """Inject a model instance for testing or runtime override.

        Args:
            model: A risk-model-like object with a ``predict(principal, term)``
                method.
        """
        self.__model = model

    def handle(self, event: Event) -> None:
        """Score new loans and emit early-warning signals.

        Args:
            event: The incoming event. Only LOAN_ORIGINATED events are processed.
        """
        if event.event_type == EventType.LOAN_ORIGINATED:
            dp: float = get_finite(event.payload, "default_probability")
            borrower: str = get_non_empty(event.payload, "borrower")
            if dp > 0.3:
                self.emit(
                    EventType.RISK_EARLY_WARNING,
                    {
                        "borrower": borrower,
                        "default_probability": dp,
                    },
                    correlation_id=event.correlation_id,
                )
            if self.__model:
                try:
                    principal: float = get_finite(event.payload, "principal")
                    term: float = get_finite(event.payload, "term", 1.0)
                    score: float = self.__model.predict(principal, term)
                except Exception as exc:
                    logger.exception("risk scoring failed for {}: {}", borrower, exc)
                    if self.metrics_collector:
                        self.metrics_collector.increment(
                            "risk.scoring.failures",
                            {
                                "service": self.service_id,
                                "borrower": borrower,
                            },
                        )
                    score = -1.0
                self.emit(
                    EventType.RISK_SCORED,
                    {
                        "borrower": borrower,
                        "score": score,
                    },
                    correlation_id=event.correlation_id,
                )

    def health_check(self) -> dict[str, Any]:
        """Return risk-specific health info.

        Returns:
            Dict with base health plus model_present flag.
        """
        return {
            **super().health_check(),
            "model_present": self.__model is not None,
        }
