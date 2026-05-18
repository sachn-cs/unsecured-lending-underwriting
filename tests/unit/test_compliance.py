"""Unit tests for RBI compliance modules."""

from __future__ import annotations

import pytest

from ulu.compliance.kyc_aml import KycAmlService
from ulu.compliance.rbi_dlg import RbiDlgCompliance
from ulu.compliance.reporting import RbiReporter
from ulu.domain.users import AmlStatus, KycStatus, User, UserRole


class TestRbiDlgCompliance:
    def test_physical_recovery_limit(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.physical_recovery_limit(1000.0) == 50.0

    def test_compute_physical_recovery_capped(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.compute_physical_recovery(200.0, 1000.0) == 50.0

    def test_compute_physical_recovery_below_cap(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.compute_physical_recovery(30.0, 1000.0) == 30.0

    def test_remaining_bank_absorption(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.remaining_bank_absorption(200.0, 1000.0) == 150.0

    def test_can_originate_true(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.can_originate(1000.0, 50.0) is True

    def test_can_originate_false(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.can_originate(1000.0, 49.0) is False

    def test_boundary_exact_cap(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.can_originate(1000.0, 50.0) is True
        assert dlg.can_originate(1000.0, 49.999) is False

    def test_invalid_ratio_rejected(self) -> None:
        with pytest.raises(ValueError):
            RbiDlgCompliance(dlg_cap_ratio=-0.01)
        with pytest.raises(ValueError):
            RbiDlgCompliance(dlg_cap_ratio=1.1)

    def test_negative_logical_loss_clamped(self) -> None:
        dlg = RbiDlgCompliance(dlg_cap_ratio=0.05)
        assert dlg.compute_physical_recovery(-50.0, 1000.0) == 0.0


class TestKycAmlService:
    def test_verify_kyc_not_implemented(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        with pytest.raises(NotImplementedError):
            svc.verify_kyc(user, "ABCDE1234F", "hash123")

    def test_verify_kyc_rejected_missing_pan(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        status = svc.verify_kyc(user, "", "hash123")
        assert status == KycStatus.REJECTED

    def test_screen_aml_clear(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        status, event = svc.screen_aml(user, watchlist_hit=False)
        assert status == AmlStatus.CLEAR
        assert event is None

    def test_screen_aml_frozen(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        status, event = svc.screen_aml(user, watchlist_hit=True)
        assert status == AmlStatus.FROZEN
        assert event is not None
        assert event.new_status == "frozen"

    def test_kyc_state_machine_transition(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        event = svc.transition_kyc(user, KycStatus.VERIFIED, "test")
        assert user.kyc_status == KycStatus.VERIFIED
        assert event is not None
        assert event.new_status == "verified"

    def test_invalid_kyc_transition_rejected(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        user.kyc_status = KycStatus.VERIFIED
        with pytest.raises(ValueError):
            svc.transition_kyc(user, KycStatus.REJECTED)

    def test_is_compliant_requires_both(self) -> None:
        svc = KycAmlService()
        user = User("u1", UserRole.BORROWER)
        assert svc.is_compliant(user) is False
        user.kyc_status = KycStatus.VERIFIED
        user.aml_status = AmlStatus.CLEAR
        assert svc.is_compliant(user) is True


class TestRbiReporter:
    def test_generate_portfolio_report(self) -> None:
        reporter = RbiReporter()
        report = reporter.generate_portfolio_report(
            total_outstanding=5000.0,
            total_earned_credit=2000.0,
            total_defaults=100.0,
            dlg_pool_balance=500.0,
        )
        assert report["report_type"] == "portfolio_summary"
        assert report["dlg_utilization_ratio"] == 0.2

    def test_generate_dlg_invocation_report(self) -> None:
        reporter = RbiReporter()
        report = reporter.generate_dlg_invocation_report(
            loan_id="l1", recovery_amount=50.0, invoked_at="2026-01-01T00:00:00"
        )
        assert report["report_type"] == "dlg_invocation"
        assert report["compliance_framework"] == "RBI_Digital_Lending_Directions_2023"
