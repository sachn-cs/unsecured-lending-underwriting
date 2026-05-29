"""ML risk scoring and early-warning signals.

Optionally integrates with sklearn-based risk models.  The risk model
path is configurable via the environment or the shared store.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService
from underwrite.validate import get_finite, get_non_empty

logger = logging.getLogger(__name__)

try:
    from underwrite.services.risk.model import RiskModel
    HAS_RISK_MODEL: bool = True
except ImportError:
    HAS_RISK_MODEL = False


class RiskService(NanoService):
    """Computes default-probability scores and triggers early-warning alerts."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the risk service and optionally load an ML model.

        Args:
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(**kwargs)
        self.__model: Any | None = None
        if HAS_RISK_MODEL:
            model_path: str = os.environ.get("RISK_MODEL_PATH", "")
            self.__model = RiskModel(model_path) if model_path else RiskModel()

    def set_model(self, model: Any) -> None:
        """Inject a model instance for testing or runtime override.

        Args:
            model: A risk-model-like object with a ``predict(principal, term)`` method.
        """
        self.__model = model

    def handle(self, event: Event) -> None:
        """Score new loans and emit early-warning signals for high-risk borrowers.

        Args:
            event: The incoming event. Only LOAN_ORIGINATED events are processed.
        """
        if event.event_type == EventType.LOAN_ORIGINATED:
            dp: float = get_finite(event.payload, "default_probability")
            borrower: str = get_non_empty(event.payload, "borrower")
            if dp > 0.3:
                self.emit(EventType.RISK_EARLY_WARNING, {
                    "borrower": borrower,
                    "default_probability": dp,
                },
                          correlation_id=event.correlation_id)
            if self.__model:
                try:
                    principal: float = get_finite(event.payload, "principal")
                    term: float = get_finite(event.payload, "term", 1.0)
                    score: float = self.__model.predict(principal, term)
                except Exception as exc:
                    logger.exception("risk scoring failed for %s: %s", borrower,
                                     exc)
                    if self.metrics_collector:
                        self.metrics_collector.increment(
                            "risk.scoring.failures", {
                                "service": self.service_id,
                                "borrower": borrower,
                            })
                    score = -1.0
                self.emit(EventType.RISK_SCORED, {
                    "borrower": borrower,
                    "score": score,
                },
                          correlation_id=event.correlation_id)

    def health_check(self) -> dict[str, Any]:
        """Risk-specific health: reports model presence."""
        return {
            **super().health_check(),
            "model_present": self.__model is not None,
        }
