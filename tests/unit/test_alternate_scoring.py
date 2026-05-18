"""Unit tests for alternate data scoring."""

from __future__ import annotations

import pytest

from ulu.risk.alternate_scoring import (
    AlternateDataScoringService,
    TelecomData,
    UpiTransactionPattern,
    UtilityPaymentPattern,
)


class TestAlternateDataScoringService:
    def test_score_upi_pattern(self) -> None:
        svc = AlternateDataScoringService()
        pattern = UpiTransactionPattern(
            monthly_volume=60000.0,
            avg_transaction_size=500.0,
            merchant_diversity_score=25,
            failure_rate=0.01,
            late_night_ratio=0.1,
        )
        score = svc.score_upi_pattern(pattern)
        assert 0.0 <= score <= 1.0
        assert score > 0.5

    def test_score_upi_zero_volume(self) -> None:
        svc = AlternateDataScoringService()
        pattern = UpiTransactionPattern(
            monthly_volume=0.0,
            avg_transaction_size=0.0,
            merchant_diversity_score=0,
            failure_rate=0.0,
            late_night_ratio=0.0,
        )
        assert svc.score_upi_pattern(pattern) == 0.0

    def test_score_telecom(self) -> None:
        svc = AlternateDataScoringService()
        data = TelecomData(
            tenure_months=36,
            on_time_payment_ratio=0.95,
            average_monthly_bill=500.0,
            plan_category="postpaid",
        )
        score = svc.score_telecom(data)
        assert 0.0 <= score <= 1.0
        assert score > 0.8

    def test_score_utility(self) -> None:
        svc = AlternateDataScoringService()
        pattern = UtilityPaymentPattern(
            electricity_on_time_ratio=0.9,
            water_on_time_ratio=0.85,
            gas_on_time_ratio=0.95,
            avg_monthly_spend=3000.0,
        )
        score = svc.score_utility(pattern)
        assert score == pytest.approx(0.9, rel=1e-2)

    def test_composite_with_all_signals(self) -> None:
        svc = AlternateDataScoringService()
        result = svc.composite_alternate_score(
            upi=UpiTransactionPattern(
                monthly_volume=60000.0,
                avg_transaction_size=500.0,
                merchant_diversity_score=25,
                failure_rate=0.01,
                late_night_ratio=0.1,
            ),
            telecom=TelecomData(
                tenure_months=36,
                on_time_payment_ratio=0.95,
                average_monthly_bill=500.0,
                plan_category="postpaid",
            ),
            utility=UtilityPaymentPattern(
                electricity_on_time_ratio=0.9,
                water_on_time_ratio=0.85,
                gas_on_time_ratio=0.95,
                avg_monthly_spend=3000.0,
            ),
        )
        assert result["data_availability"] == "full"
        assert 0.0 <= result["score"] <= 1.0
        assert "upi" in result["components"]
        assert "telecom" in result["components"]
        assert "utility" in result["components"]

    def test_composite_with_partial_signals(self) -> None:
        svc = AlternateDataScoringService()
        result = svc.composite_alternate_score(
            upi=UpiTransactionPattern(
                monthly_volume=60000.0,
                avg_transaction_size=500.0,
                merchant_diversity_score=25,
                failure_rate=0.01,
                late_night_ratio=0.1,
            ),
        )
        assert result["data_availability"] == "partial"
        assert "upi" in result["components"]
        assert "telecom" not in result["components"]

    def test_composite_no_signals(self) -> None:
        svc = AlternateDataScoringService()
        result = svc.composite_alternate_score()
        assert result["score"] == 0.0
        assert result["data_availability"] == "none"
