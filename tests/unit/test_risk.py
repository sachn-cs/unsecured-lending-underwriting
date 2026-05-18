"""Unit tests for risk and stress testing modules."""

from __future__ import annotations

from ulu.risk.scoring import CreditScoringService
from ulu.risk.stress import StressTestEngine


class TestCreditScoringService:
    def test_estimate_default_probability_positive(self) -> None:
        svc = CreditScoringService()
        p = svc.estimate_default_probability(cash_flow=50000.0, average_balance=10000.0, transaction_frequency=10)
        assert 0.0 < p < 1.0

    def test_estimate_default_probability_negative_cash_flow(self) -> None:
        svc = CreditScoringService()
        p = svc.estimate_default_probability(cash_flow=-100.0, average_balance=10000.0, transaction_frequency=10)
        assert p == 0.99

    def test_estimate_default_probability_zero_balance(self) -> None:
        svc = CreditScoringService()
        p = svc.estimate_default_probability(cash_flow=50000.0, average_balance=0.0, transaction_frequency=10)
        assert p == 0.99


class TestStressTestEngine:
    def test_simulate_empty_borrowers(self) -> None:
        engine = StressTestEngine(seed=7)
        result = engine.simulate_correlated_defaults([], correlation=0.3)
        assert result["expected_loss"] == 0.0

    def test_simulate_uncorrelated(self) -> None:
        engine = StressTestEngine(seed=7)
        borrowers = [
            {"default_probability": 0.1, "principal": 1000.0},
            {"default_probability": 0.2, "principal": 2000.0},
        ]
        result = engine.simulate_correlated_defaults(borrowers, correlation=0.0, n_simulations=1000)
        assert result["expected_loss"] > 0.0
        assert result["var_95"] >= result["expected_loss"]

    def test_simulate_correlated(self) -> None:
        engine = StressTestEngine(seed=7)
        borrowers = [
            {"default_probability": 0.1, "principal": 1000.0},
            {"default_probability": 0.2, "principal": 2000.0},
        ]
        result = engine.simulate_correlated_defaults(borrowers, correlation=0.8, n_simulations=1000)
        assert result["var_99"] >= result["var_95"]
