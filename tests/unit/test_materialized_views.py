"""Unit tests for portfolio summary materialized view."""

from __future__ import annotations

from ulu.infra.materialized_views import PortfolioSummaryService


class TestPortfolioSummaryService:
    def test_refresh_and_get(self) -> None:
        svc = PortfolioSummaryService()
        principal = {"u1": 1000.0, "u2": 500.0}
        earned = {"u1": 200.0, "u2": 50.0}
        svc.refresh(principal, earned)
        s1 = svc.get("u1")
        assert s1 is not None
        assert s1.total_principal == 1000.0
        assert s1.total_earned_credit == 200.0
        assert s1.total_outstanding == 800.0

    def test_refresh_with_recovery(self) -> None:
        svc = PortfolioSummaryService()
        principal = {"u1": 1000.0}
        earned = {"u1": 200.0}
        recovered = {"u1": 100.0}
        svc.refresh(principal, earned, recovered=recovered)
        s1 = svc.get("u1")
        assert s1 is not None
        assert s1.total_outstanding == 700.0
        assert s1.total_recovered == 100.0

    def test_get_missing(self) -> None:
        svc = PortfolioSummaryService()
        svc.refresh({}, {})
        assert svc.get("nobody") is None

    def test_summary(self) -> None:
        svc = PortfolioSummaryService()
        principal = {"u1": 1000.0, "u2": 500.0}
        earned = {"u1": 200.0, "u2": 50.0}
        svc.refresh(principal, earned)
        summary = svc.summary()
        assert summary["user_count"] == 2
        assert summary["total_principal"] == 1500.0
        assert summary["total_earned_credit"] == 250.0
        assert summary["total_outstanding"] == 1250.0

    def test_total_defaults(self) -> None:
        svc = PortfolioSummaryService()
        principal = {"u1": 1000.0}
        earned = {"u1": 0.0}
        defaults = {"u1": 300.0}
        svc.refresh(principal, earned, defaults=defaults)
        assert svc.total_defaults() == 300.0
