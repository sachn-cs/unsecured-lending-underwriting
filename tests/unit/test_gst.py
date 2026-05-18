"""Unit tests for GST verification service."""

from __future__ import annotations

from ulu.compliance.gst import GstReturn, GstVerificationService


class TestGstVerificationService:
    def test_verify_valid_gstin(self) -> None:
        svc = GstVerificationService()
        result = svc.verify_gstin("27AAPFU0939F1ZV")
        assert result["valid"] is True

    def test_verify_invalid_gstin_short(self) -> None:
        svc = GstVerificationService()
        result = svc.verify_gstin("SHORT")
        assert result["valid"] is False

    def test_fetch_returns_stub(self) -> None:
        svc = GstVerificationService()
        returns = svc.fetch_returns("27AAPFU0939F1ZV", "2025-26")
        assert returns == []

    def test_filing_consistency_score(self) -> None:
        svc = GstVerificationService()
        returns = [
            GstReturn("g1", "2025-04", "2025-05-01", 100000.0, 5000.0, "filed"),
            GstReturn("g1", "2025-05", "2025-06-01", 120000.0, 6000.0, "filed"),
            GstReturn("g1", "2025-06", "2025-07-10", 110000.0, 5500.0, "late"),
        ]
        score = svc.filing_consistency_score(returns)
        assert 0.0 < score < 1.0

    def test_filing_consistency_score_empty(self) -> None:
        svc = GstVerificationService()
        assert svc.filing_consistency_score([]) == 0.0
