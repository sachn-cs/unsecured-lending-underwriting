"""Unit tests for dynamic rate pricing."""

from __future__ import annotations

import pytest

from ulu.core.dynamic_pricing import DynamicPricingService


class TestDynamicPricingService:
    def test_compute_rates_zero_utilization(self) -> None:
        svc = DynamicPricingService(base_protocol_rate=0.1, base_delegation_rate=0.05)
        rate = svc.compute_rates(risk_score=0.0, utilization=0.0)
        assert rate.protocol_rate == pytest.approx(0.1)
        assert rate.delegation_rate == pytest.approx(0.05)

    def test_compute_rates_max_risk(self) -> None:
        svc = DynamicPricingService(base_protocol_rate=0.1, risk_sensitivity=0.5)
        rate = svc.compute_rates(risk_score=1.0, utilization=0.0)
        assert rate.protocol_rate == pytest.approx(0.6)
        assert rate.risk_adjustment == pytest.approx(0.5)

    def test_compute_rates_high_utilization_lowers_delegation(self) -> None:
        svc = DynamicPricingService(base_delegation_rate=0.1, utilization_sensitivity=0.3)
        rate = svc.compute_rates(risk_score=0.0, utilization=1.0)
        assert rate.delegation_rate == pytest.approx(0.0)
        assert rate.utilization_adjustment == pytest.approx(0.3)

    def test_compute_rates_capped(self) -> None:
        svc = DynamicPricingService(
            base_protocol_rate=0.9,
            risk_sensitivity=0.5,
            max_rate_cap=1.0,
        )
        rate = svc.compute_rates(risk_score=1.0, utilization=1.0)
        assert rate.protocol_rate == pytest.approx(1.0)

    def test_compute_rates_clamps_inputs(self) -> None:
        svc = DynamicPricingService()
        rate = svc.compute_rates(risk_score=-0.5, utilization=2.0)
        assert rate.protocol_rate >= 0.0
        assert rate.delegation_rate >= 0.0
