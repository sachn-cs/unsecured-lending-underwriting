"""Risk scoring model (optional sklearn wrapper).

Loads a pre-trained model from a pickle file or falls back to a
heuristic default-probability calculator.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("underwrite")


class RiskModel:
    """Wraps an sklearn model or uses a heuristic fallback."""

    def __init__(self, model_path: str = "") -> None:
        """Load a pre-trained model from a pickle/joblib file or use a heuristic fallback.

        Args:
            model_path: Path to a serialised model file. If empty or missing,
                only the heuristic fallback is used.
        """
        self.__model: Any | None = None
        if model_path and Path(model_path).exists():
            self.__verify_integrity(model_path)
            try:
                import joblib
                self.__model = joblib.load(model_path)
            except ImportError:
                logger.warning(
                    "joblib not available, falling back to pickle for %s",
                    model_path)
                import pickle
                with open(model_path, "rb") as fh:
                    self.__model = pickle.load(fh)

    @staticmethod
    def __verify_integrity(model_path: str) -> None:
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
        if self.__model is not None:
            try:
                result = self.__model.predict([[principal, term]])
                return float(result[0])
            except Exception as exc:
                logger.exception("risk model predict failed: %s", exc)
        return self.__heuristic(principal, term)

    @staticmethod
    def __heuristic(principal: float, term: float) -> float:
        safe_term: float = max(term, 1.0)
        if principal <= 0:
            return 0.0
        raw: float = (principal / 1_000_000.0) * (1.0 / safe_term)
        return min(max(raw, 0.01), 0.5)
