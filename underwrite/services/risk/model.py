"""Risk scoring model (optional sklearn wrapper).

Loads a pre-trained model from a joblib file or reconstructs from a
JSON parameter file. Falls back to a heuristic default-probability
calculator when no model file is available.
"""

from __future__ import annotations

import hashlib
import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from underwrite.__logger__ import logger

__all__ = [
    "HeuristicStrategy",
    "JoblibModelStrategy",
    "JsonModelStrategy",
    "RiskModel",
    "RiskScoringStrategy",
    "StrategyRegistry",
    "register_strategy",
    "get_strategy",
]

class StrategyRegistry:
    """Thread-safe registry for risk-scoring strategy classes.

    Strategies are registered by name and looked up at model-load time,
    enabling plugin-like discovery of third-party model wrappers.
    """

    def __init__(self) -> None:
        self.__strategies: dict[str, type[RiskScoringStrategy]] = {}
        self.__lock: threading.Lock = threading.Lock()

    def register(self, name: str, strategy_cls: type[RiskScoringStrategy]) -> None:
        """Register a strategy class under *name*.

        Args:
            name: Short identifier (e.g. ``"xgboost"``, ``"linear"``).
            strategy_cls: A concrete ``RiskScoringStrategy`` subclass.

        Raises:
            TypeError: If *strategy_cls* is not a ``RiskScoringStrategy``
                subclass.
        """
        if not (isinstance(strategy_cls, type) and issubclass(strategy_cls, RiskScoringStrategy)):
            raise TypeError(f"{strategy_cls} is not a RiskScoringStrategy subclass")
        with self.__lock:
            self.__strategies[name] = strategy_cls

    def get(self, name: str) -> type[RiskScoringStrategy] | None:
        """Return the strategy registered under *name*, or ``None``.

        Args:
            name: The strategy name to look up.

        Returns:
            The registered strategy class, or None.
        """
        with self.__lock:
            return self.__strategies.get(name)

module_strategy_registry: StrategyRegistry = StrategyRegistry()

def register_strategy(name: str, strategy_cls: type[RiskScoringStrategy]) -> None:
    """Register a risk-scoring strategy class by name for plugin-like discovery.

    Args:
        name: Short name (e.g. ``"xgboost"``, ``"linear"``).
        strategy_cls: A concrete ``RiskScoringStrategy`` subclass.
    """
    module_strategy_registry.register(name, strategy_cls)

def get_strategy(name: str) -> type[RiskScoringStrategy] | None:
    """Return a previously registered strategy class, or ``None``.

    Args:
        name: The strategy name to look up.

    Returns:
        The registered strategy class, or None.
    """
    return module_strategy_registry.get(name)

class RiskScoringStrategy(ABC):
    """Abstract strategy for risk scoring models.

    Implementors must provide a ``predict(principal, term)`` method
    that returns a default-probability score in [0.0, 1.0].
    """

    @abstractmethod
    def predict(self, principal: float, term: float) -> float: ...

class HeuristicStrategy(RiskScoringStrategy):
    """Heuristic fallback based on principal-to-term ratio."""

    def predict(self, principal: float, term: float) -> float:
        """Compute a heuristic default-probability score.

        Args:
            principal: Loan principal amount.
            term: Loan term.

        Returns:
            A score in [0.01, 0.5].
        """
        safe_term: float = max(term, 1.0)
        if principal <= 0:
            return 0.0
        raw: float = (principal / 1_000_000.0) * (1.0 / safe_term)
        return min(max(raw, 0.01), 0.5)

class JsonModelStrategy(RiskScoringStrategy):
    """Minimal linear model reconstructed from JSON-serialized parameters."""

    def __init__(self, params: dict[str, Any]) -> None:
        self.__coef: list[float] = params.get("coef_", [0.0, 0.0])
        self.__intercept: float = params.get("intercept_", 0.0)

    def predict(self, principal: float, term: float) -> float:
        """Predict using a linear model from JSON parameters.

        Args:
            principal: Loan principal amount.
            term: Loan term.

        Returns:
            A score in [0.0, 1.0].
        """
        score = principal * self.__coef[0] + term * self.__coef[1] + self.__intercept
        return min(max(score, 0.0), 1.0)

class JoblibModelStrategy(RiskScoringStrategy):
    """Wraps a joblib-loaded sklearn-compatible model."""

    def __init__(self, model: Any) -> None:
        self.__model = model

    def predict(self, principal: float, term: float) -> float:
        """Predict using a joblib-loaded sklearn model.

        Args:
            principal: Loan principal amount.
            term: Loan term.

        Returns:
            The model's prediction as a float.
        """
        result = self.__model.predict([[principal, term]])
        return float(result[0])

class RiskModel:
    """Wraps a trained model or uses a heuristic fallback.

    Accepts either a pre-built ``RiskScoringStrategy`` instance or a
    model file path (joblib / JSON).  When neither is provided, falls
    back to ``HeuristicStrategy``.
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
            model_path: Path to a serialized model file. If empty or missing,
                only the heuristic fallback is used.
            strategy: An optional ``RiskScoringStrategy`` instance.  When
                provided, *model_path* is ignored.
        """
        self.__strategy: RiskScoringStrategy
        if strategy is not None:
            self.__strategy = strategy
        elif model_path and Path(model_path).exists():
            self.__verify_integrity(model_path)
            self.__strategy = self.load_strategy(model_path)
        else:
            self.__strategy = HeuristicStrategy()

    @staticmethod
    def __verify_integrity(model_path: str) -> None:
        """Verify model file integrity using SHA-256.

        Args:
            model_path: Path to the model file.

        Raises:
            ValueError: If integrity check fails.
        """
        import os as _os

        expected = _os.environ.get("RISK_MODEL_SHA256", "")
        sidecar = Path(f"{model_path}.sha256")
        if not expected and sidecar.exists():
            expected = sidecar.read_text().strip()
        if not expected:
            raise ValueError(
                "Model integrity check requires either RISK_MODEL_SHA256 "
                f"environment variable or a {model_path}.sha256 sidecar file"
            )
        with open(model_path, "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        if actual != expected:
            raise ValueError(f"Model integrity check failed: expected {expected}, got {actual}")

    def predict(self, principal: float, term: float) -> float:
        """Return a default-probability score in [0.0, 1.0].

        Args:
            principal: Loan principal amount.
            term: Loan term.

        Returns:
            A default-probability score.
        """
        import math as math_mod

        if not math_mod.isfinite(principal) or not math_mod.isfinite(term):
            logger.warning(
                "non-finite inputs to risk model: principal={!r}, term={!r}",
                principal,
                term,
            )
            principal = max(principal, 0.0) if math_mod.isfinite(principal) else 0.0
            term = max(term, 1.0) if math_mod.isfinite(term) else 1.0
        try:
            return self.__strategy.predict(principal, term)
        except Exception as exc:
            logger.exception("risk model predict failed: {}", exc)
            return HeuristicStrategy().predict(principal, term)

    @property
    def strategy(self) -> RiskScoringStrategy:
        """Active scoring strategy. Test extension point."""
        return self.__strategy

    @strategy.setter
    def strategy(self, value: RiskScoringStrategy) -> None:
        self.__strategy = value

    @staticmethod
    def load_strategy(model_path: str) -> RiskScoringStrategy:
        """Load a model file and return the appropriate strategy.

        Supports JSON-serialized model parameters (``coef_``, ``intercept_``).
        Joblib support is gated behind the ``UNDERWRITE_ALLOW_JOBLIB``
        environment variable — it must be set to ``"true"`` before importing
        this module to enable arbitrary pickle deserialization.

        Args:
            model_path: Path to the serialized model file.

        Returns:
            A ``RiskScoringStrategy`` instance.

        Raises:
            ValueError: If the model file cannot be parsed.
        """
        import os as _os

        env_allowed = _os.environ.get("UNDERWRITE_ALLOW_JOBLIB", "").lower()
        if env_allowed == "true":
            try:
                import joblib

                model = joblib.load(model_path)
                if callable(getattr(model, "predict", None)):
                    return JoblibModelStrategy(model)
                raise ValueError("joblib-loaded object has no predict method")
            except ImportError:
                logger.info("joblib not available, falling back to JSON load")
            except Exception as exc:
                logger.exception("joblib load failed for {}: {}", model_path, exc)
        else:
            logger.info("joblib disabled; set UNDERWRITE_ALLOW_JOBLIB=true to enable")

        try:
            with open(model_path) as fh:
                params = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Failed to parse model file {model_path}: {exc}") from exc

        if not isinstance(params, dict):
            raise ValueError(f"JSON model file must contain a JSON object, got {type(params).__name__}")
        return JsonModelStrategy(params)
