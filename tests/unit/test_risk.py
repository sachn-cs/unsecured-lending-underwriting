"""Unit tests for risk and stress testing modules."""

from __future__ import annotations

from ulu.risk.early_warning import EarlyWarningService, RiskSignal
from ulu.risk.scoring import CreditScoringService
from ulu.risk.stress import StressTestEngine


class TestEarlyWarningService:
    def test_no_signals_when_all_metrics_healthy(self) -> None:
        svc = EarlyWarningService()
        result = svc.evaluate_borrower()
        assert result["signals"] == []
        assert result["score"] == 0.0
        assert result["risk_level"] == "low"

    def test_payment_delay_medium(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_payment_delay(2.0)
        assert signal is not None
        assert signal.severity == "medium"

    def test_payment_delay_high(self) -> None:
        svc = EarlyWarningService(payment_delay_threshold_days=3.0)
        signal = svc.evaluate_payment_delay(5.0)
        assert signal is not None
        assert signal.severity == "high"

    def test_cash_flow_drop_medium(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_cash_flow_drop(current_monthly_inflow=7000.0, avg_monthly_inflow=10000.0)
        assert signal is not None
        assert signal.severity == "medium"

    def test_cash_flow_drop_high(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_cash_flow_drop(current_monthly_inflow=4000.0, avg_monthly_inflow=10000.0)
        assert signal is not None
        assert signal.severity == "high"

    def test_cash_flow_drop_zero_average(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_cash_flow_drop(current_monthly_inflow=1000.0, avg_monthly_inflow=0.0)
        assert signal is None

    def test_bounce_events_below_threshold(self) -> None:
        svc = EarlyWarningService(bounce_event_threshold=3)
        signal = svc.evaluate_bounce_events(2)
        assert signal is None

    def test_bounce_events_at_threshold(self) -> None:
        svc = EarlyWarningService(bounce_event_threshold=2)
        signal = svc.evaluate_bounce_events(2)
        assert signal is not None
        assert signal.severity == "high"

    def test_utilization_spike_no_history(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_utilization_spike(current_utilization=0.3, historical_avg_utilization=0.0)
        assert signal is not None
        assert signal.metric_value == 0.3

    def test_utilization_spike_medium(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_utilization_spike(current_utilization=0.13, historical_avg_utilization=0.1)
        assert signal is not None
        assert signal.severity == "medium"

    def test_utilization_spike_high(self) -> None:
        svc = EarlyWarningService()
        signal = svc.evaluate_utilization_spike(current_utilization=0.6, historical_avg_utilization=0.1)
        assert signal is not None
        assert signal.severity == "high"

    def test_composite_score_computes_correctly(self) -> None:
        svc = EarlyWarningService()
        result = svc.evaluate_borrower(days_overdue=5.0, bounce_count=3)
        assert result["score"] == 12.0
        assert result["risk_level"] == "medium"

    def test_score_to_level_boundary_low(self) -> None:
        assert EarlyWarningService._score_to_level(0.0) == "low"
        assert EarlyWarningService._score_to_level(5.0) == "low"

    def test_score_to_level_boundary_medium(self) -> None:
        assert EarlyWarningService._score_to_level(6.0) == "medium"
        assert EarlyWarningService._score_to_level(15.0) == "medium"

    def test_score_to_level_boundary_high(self) -> None:
        assert EarlyWarningService._score_to_level(16.0) == "high"
        assert EarlyWarningService._score_to_level(30.0) == "high"

    def test_score_to_level_boundary_critical(self) -> None:
        assert EarlyWarningService._score_to_level(31.0) == "critical"

    def test_score_capped_at_100(self) -> None:
        signals = [RiskSignal("x", "critical", "", 1.0, 1.0) for _ in range(12)]
        assert EarlyWarningService._compute_score(signals) == 100.0


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
