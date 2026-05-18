"""Unit tests for legal notice generation."""

from __future__ import annotations

import pytest

from ulu.servicing.notices import LegalNoticeService


class TestLegalNoticeService:
    def test_generate_60_day_notice(self) -> None:
        svc = LegalNoticeService()
        notice = svc.generate_notice(
            borrower_id="b1",
            loan_id="loan-1",
            days_overdue=65,
            principal_outstanding=100000.0,
            notice_type="60_day",
            generated_at="2026-05-18",
        )
        assert notice.notice_type == "60_day"
        assert "SARFAESI" in notice.content
        assert "b1" in notice.content

    def test_generate_90_day_notice(self) -> None:
        svc = LegalNoticeService()
        notice = svc.generate_notice(
            borrower_id="b1",
            loan_id="loan-1",
            days_overdue=95,
            principal_outstanding=100000.0,
            notice_type="90_day",
            generated_at="2026-05-18",
            earlier_notice_date="2026-03-18",
        )
        assert notice.notice_type == "90_day"
        assert "DEMAND NOTICE" in notice.content

    def test_generate_120_day_notice(self) -> None:
        svc = LegalNoticeService()
        notice = svc.generate_notice(
            borrower_id="b1",
            loan_id="loan-1",
            days_overdue=125,
            principal_outstanding=100000.0,
            notice_type="120_day",
            generated_at="2026-05-18",
        )
        assert notice.notice_type == "120_day"
        assert "POSSESSION NOTICE" in notice.content

    def test_unknown_notice_type(self) -> None:
        svc = LegalNoticeService()
        with pytest.raises(ValueError, match="unknown notice type"):
            svc.generate_notice("b1", "loan-1", 10, 1000.0, "invalid_type")

    def test_get_notice_type(self) -> None:
        svc = LegalNoticeService()
        assert svc.get_notice_type(130) == "120_day"
        assert svc.get_notice_type(95) == "90_day"
        assert svc.get_notice_type(60) == "60_day"
        assert svc.get_notice_type(30) == "reminder"
