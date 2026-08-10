# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for RiskModel and StrategyRegistry."""

from __future__ import annotations

from typing import Any, cast

import pytest

from underwrite.services.risk.model import (
    HeuristicStrategy,
    RiskModel,
    StrategyRegistry,
)


class TestStrategyRegistry:
    def test_register_and_get(self) -> None:
        registry = StrategyRegistry()
        registry.register("heuristic", HeuristicStrategy)
        cls = registry.get("heuristic")
        assert cls is HeuristicStrategy

    def test_get_unknown_returns_none(self) -> None:
        registry = StrategyRegistry()
        assert registry.get("nonexistent") is None

    def test_register_rejects_non_strategy(self) -> None:
        registry = StrategyRegistry()
        with pytest.raises(TypeError):
            registry.register("bad", cast(Any, object))

    def test_register_double_allowed(self) -> None:
        registry = StrategyRegistry()
        registry.register("dup", HeuristicStrategy)
        registry.register("dup", HeuristicStrategy)
        cls = registry.get("dup")
        assert cls is HeuristicStrategy


class TestRiskModel:
    def test_heuristic_fallback(self) -> None:
        model = RiskModel()
        score = model.predict(100000.0, 12.0)
        assert 0.0 <= score <= 1.0

    def test_predict_clamps_to_range(self) -> None:
        model = RiskModel()
        score = model.predict(1e9, 1.0)
        assert 0.0 <= score <= 1.0

    def test_invalid_inputs_sanitized(self) -> None:
        model = RiskModel()
        score = model.predict(float("nan"), 12.0)
        assert isinstance(score, float)

    def test_negative_principal_returns_zero_dp(self) -> None:
        model = RiskModel()
        score = model.predict(-100.0, 12.0)
        assert 0.0 <= score <= 1.0

    def test_load_strategy_rejects_bad_path(self) -> None:
        with pytest.raises(ValueError):
            RiskModel.load_strategy("/nonexistent/model.joblib")
