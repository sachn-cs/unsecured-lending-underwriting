"""Risk scoring model (optional sklearn wrapper).

Loads a pre-trained model from a joblib file or reconstructs from a
JSON parameter file. Falls back to a heuristic default-probability
calculator when no model file is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "HeuristicStrategy",
    "JoblibModelStrategy",
    "JsonModelStrategy",
    "RiskModel",
    "RiskScoringStrategy",
    "register_strategy",
    "get_strategy",
]


# -- Strategy pattern ---------------------------------------------------------

class RiskScoringStrategy(ABC):
    """Abstract strategy for risk scoring models.

    Implementors must provide a ``predict(principal, term)`` method
    that returns a default-probability score in [0.0, 1.0].
    """

    @abstractmethod
    def predict(self, principal: float, term: float) -> float:
        ...


_strategies: dict[str, type[RiskScoringStrategy]] = {}
_strategies_lock: threading.Lock = threading.Lock()


def register_strategy(name: str, strategy_cls: type[RiskScoringStrategy]) -> None:
    """Register a risk-scoring strategy class by name for plugin-like discovery.

    Args:
        name: Short name (e.g. ``"xgboost"``, ``"linear"``).
        strategy_cls: A concrete ``RiskScoringStrategy`` subclass.
    """
    with _strategies_lock:
        _strategies[name] = strategy_cls


def get_strategy(name: str) -> type[RiskScoringStrategy] | None:
    """Return a previously registered strategy class, or ``None``."""
    with _strategies_lock:
        return _strategies.get(name)


# -- Concrete strategies ------------------------------------------------------

class HeuristicStrategy(RiskScoringStrategy):
    """Heuristic fallback based on principal-to-term ratio."""

    def predict(self, principal: float, term: float) -> float:
        safe_term: float = max(term, 1.0)
        if principal <= 0:
            return 0.0
        raw: float = (principal / 1_000_000.0) * (1.0 / safe_term)
        return min(max(raw, 0.01), 0.5)


class JsonModelStrategy(RiskScoringStrategy):
    """Minimal linear model reconstructed from JSON-serialised parameters."""

    def __init__(self, params: dict[str, Any]) -> None:
        self.__coef: list[float] = params.get("coef_", [0.0, 0.0])
        self.__intercept: float = params.get("intercept_", 0.0)

    def predict(self, principal: float, term: float) -> float:
        score = principal * self.__coef[0] + term * self.__coef[1] + self.__intercept
        return min(max(score, 0.0), 1.0)


class JoblibModelStrategy(RiskScoringStrategy):
    """Wraps a joblib-loaded sklearn-compatible model."""

    def __init__(self, model: Any) -> None:
        self.__model = model

    def predict(self, principal: float, term: float) -> float:
        result = self.__model.predict([[principal, term]])
        return float(result[0])


# -- Backward-compatible facade -----------------------------------------------

class RiskModel:
    """Wraps a trained model or uses a heuristic fallback.

    Accepts either a pre-built ``RiskScoringStrategy`` instance or a
    model file path (joblib / JSON).  When neither is provided, falls
    back to ``HeuristicStrategy``.

    The model must expose a ``predict(X)`` method that accepts a list
    of feature vectors and returns a list of predictions.
    """

    def __init__(
        self,
        model_path: str = "",
        strategy: RiskScoringStrategy | None = None,
    ) -> None:
        """Load a pre-trained model from a file or use a heuristic fallback.

        Supports joblib files (preferred) and JSON parameter files with
        ``coef_`` and ``intercept_`` keys.

        Args:
            model_path: Path to a serialised model file. If empty or missing,
                only the heuristic fallback is used.
            strategy: An optional ``RiskScoringStrategy`` instance.  When
                provided, *model_path* is ignored.
        """
        self.__strategy: RiskScoringStrategy
        if strategy is not None:
            self.__strategy = strategy
        elif model_path and Path(model_path).exists():
            self.__verify_integrity(model_path)
            self.__strategy = _load_strategy(model_path)
        else:
            self.__strategy = HeuristicStrategy()

    @staticmethod
    def __verify_integrity(model_path: str) -> None:
        import os
        expected = os.environ.get("RISK_MODEL_SHA256", "")
        sidecar = Path(str(model_path) + ".sha256")
        if not expected and sidecar.exists():
            expected = sidecar.read_text().strip()
        if expected:
            with open(model_path, "rb") as f:
                actual = hashlib.sha256(f.read()).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"Model integrity check failed: expected {expected}, got {actual}"
                )

    def predict(self, principal: float, term: float) -> float:
        """Returns a default-probability score in [0.0, 1.0]."""
        import math as _math
        if not _math.isfinite(principal) or not _math.isfinite(term):
            logger.warning("non-finite inputs to risk model: principal=%r, term=%r", principal, term)
            principal = max(principal, 0.0) if _math.isfinite(principal) else 0.0
            term = max(term, 1.0) if _math.isfinite(term) else 1.0
        try:
            return self.__strategy.predict(principal, term)
        except Exception as exc:
            logger.exception("risk model predict failed: %s", exc)
            # Fall back to heuristic on failure
            return HeuristicStrategy().predict(principal, term)


def _load_strategy(model_path: str) -> RiskScoringStrategy:
    """Load a model file and return the appropriate strategy.

    Tries joblib first; falls back to JSON-based reconstruction.
    """
    try:
        import joblib
        model = joblib.load(model_path)
        if callable(getattr(model, "predict", None)):
            return JoblibModelStrategy(model)
        raise ValueError("joblib-loaded object has no predict method")
    except ImportError:
        logger.info("joblib not available, falling back to JSON load")
    except Exception as exc:
        logger.warning("joblib load failed for %s: %s", model_path, exc)

    # Safe JSON fallback — no pickle, no arbitrary code execution.
    try:
        with open(model_path) as fh:
            params = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"Failed to parse model file {model_path}: {exc}") from exc

    if not isinstance(params, dict):
        raise ValueError(
            f"JSON model file must contain a JSON object, got {type(params).__name__}"
        )
    return JsonModelStrategy(params)
