"""Unit tests for collateral insurance tracking."""

from __future__ import annotations

import datetime

import pytest

from ulu.collateral.insurance import InsuranceStatus, InsuranceTrackingService


class TestInsuranceTrackingService:
    def test_register_policy(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        policy = svc.register_policy(
            "P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=365)
        )
        assert policy.policy_id == "P001"
        assert policy.status == InsuranceStatus.ACTIVE
        assert policy.escrow_id == "E001"

    def test_register_duplicate_raises(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=365))
        with pytest.raises(ValueError, match="already exists"):
            svc.register_policy(
                "P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=365)
            )

    def test_register_invalid_dates_raises(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        with pytest.raises(ValueError, match="expiry_date must be after"):
            svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, today, today)

    def test_register_negative_coverage_raises(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        with pytest.raises(ValueError, match="coverage_amount must be positive"):
            svc.register_policy("P001", "E001", "InsurerA", -100.0, 5000.0, today, today + datetime.timedelta(days=365))

    def test_cancel_policy(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=365))
        p = svc.cancel_policy("P001")
        assert p.status == InsuranceStatus.CANCELLED

    def test_mark_claimed(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=365))
        p = svc.mark_claimed("P001")
        assert p.status == InsuranceStatus.CLAIMED

    def test_mark_claimed_inactive_raises(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=365))
        svc.cancel_policy("P001")
        with pytest.raises(ValueError, match="only active"):
            svc.mark_claimed("P001")

    def test_is_expired(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        past = today - datetime.timedelta(days=1)
        policy = svc.register_policy(
            "P001", "E001", "InsurerA", 500000.0, 5000.0, past - datetime.timedelta(days=365), past
        )
        assert svc.is_expired(policy) is True

    def test_evaluate_status_expires_policy(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        past = today - datetime.timedelta(days=1)
        svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, past - datetime.timedelta(days=365), past)
        p = svc.evaluate_status("P001")
        assert p.status == InsuranceStatus.EXPIRED

    def test_list_expiring_soon(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        svc.register_policy("P001", "E001", "InsurerA", 500000.0, 5000.0, today, today + datetime.timedelta(days=10))
        svc.register_policy("P002", "E002", "InsurerB", 500000.0, 5000.0, today, today + datetime.timedelta(days=60))
        expiring = svc.list_expiring_soon(days=30)
        assert len(expiring) == 1
        assert expiring[0].policy_id == "P001"

    def test_total_coverage(self) -> None:
        svc = InsuranceTrackingService()
        today = datetime.date.today()
        svc.register_policy("P001", "E001", "InsurerA", 300000.0, 5000.0, today, today + datetime.timedelta(days=365))
        svc.register_policy("P002", "E001", "InsurerB", 200000.0, 5000.0, today, today + datetime.timedelta(days=365))
        assert svc.total_coverage("E001") == 500000.0
