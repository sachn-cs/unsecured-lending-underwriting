"""Unit tests for RBI reporting service."""

from __future__ import annotations

import pytest

from ulu.compliance.rbi_reporting import RbiReportingService


class TestRbiReportingService:
    def test_generate_monthly_report(self) -> None:
        svc = RbiReportingService()
        data = {
            "total_outstanding_principal": 1_000_000.0,
            "total_delegated_capacity": 500_000.0,
            "default_rate": 0.02,
            "avg_interest_rate": 0.15,
            "dlg_pool_balance": 50_000.0,
        }
        rows = svc.generate_report("monthly", "2026-04", data)
        assert len(rows) == 5
        assert any(r.metric_name == "default_rate" for r in rows)

    def test_generate_quarterly_report(self) -> None:
        svc = RbiReportingService()
        data = {
            "total_outstanding_principal": 3_000_000.0,
            "default_rate": 0.025,
            "npa_ratio": 0.05,
            "provision_coverage": 0.8,
            "capital_adequacy": 0.15,
            "dlg_pool_balance": 150_000.0,
        }
        rows = svc.generate_report("quarterly", "2026-Q1", data)
        assert len(rows) == 6
        assert any(r.metric_name == "npa_ratio" for r in rows)

    def test_generate_unknown_report_type(self) -> None:
        svc = RbiReportingService()
        with pytest.raises(ValueError, match="unknown report type"):
            svc.generate_report("yearly", "2026", {})

    def test_export_csv(self) -> None:
        svc = RbiReportingService()
        rows = svc.generate_report("monthly", "2026-04", {"default_rate": 0.02})
        csv_text = svc.export_csv(rows)
        assert "period" in csv_text
        assert "default_rate" in csv_text

    def test_export_csv_empty(self) -> None:
        svc = RbiReportingService()
        assert svc.export_csv([]) == ""

    def test_export_xbrl_stub(self) -> None:
        svc = RbiReportingService()
        rows = svc.generate_report("monthly", "2026-04", {"default_rate": 0.02})
        result = svc.export_xbrl_stub(rows)
        assert result["status"] == "stub"
        assert result["row_count"] == len(rows)
