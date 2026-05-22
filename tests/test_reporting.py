"""Tests for ReportingService — regulatory report generation.

Tests verify behavior through the public generate_report() method.
"""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.services.reporting.service import ReportingService


def reporting() -> ReportingService:
    return ReportingService(service_id="reporting")


class TestReportingService:

    def test_records_events(self) -> None:
        svc = reporting()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 10000
                  }))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 10000
                  }))
        report = svc.generate_report()
        assert report["total_originations"] == 1
        assert report["total_defaults"] == 1

    def test_portfolio_summary_counts(self) -> None:
        svc = reporting()
        for i in range(10):
            svc.handle(
                Event(event_type=EventType.LOAN_ORIGINATED,
                      source="test",
                      payload={
                          "borrower": f"b{i}",
                          "principal": 10000
                      }))
        for i in range(3):
            svc.handle(
                Event(event_type=EventType.DEFAULT_OCCURRED,
                      source="test",
                      payload={
                          "borrower": f"b{i}",
                          "principal": 10000
                      }))
        report = svc.generate_report()
        assert report["total_originations"] == 10
        assert report["total_defaults"] == 3
        assert report["default_rate"] == 0.3

    def test_total_principal_originated(self) -> None:
        svc = reporting()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "a",
                      "principal": 50000
                  }))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "b",
                      "principal": 150000
                  }))
        report = svc.generate_report()
        assert report["total_principal_originated"] == 200000.0

    def test_empty_report_defaults(self) -> None:
        svc = reporting()
        report = svc.generate_report()
        assert report["total_originations"] == 0
        assert report["total_defaults"] == 0
        assert report["default_rate"] == 0.0
        assert report["total_principal_originated"] == 0.0

    def test_report_type_default(self) -> None:
        svc = reporting()
        report = svc.generate_report()
        assert report["report_type"] == "portfolio_summary"

    def test_generated_at_timestamp(self) -> None:
        svc = reporting()
        report = svc.generate_report()
        assert "generated_at" in report
        assert "T" in report["generated_at"]

    def test_default_rate_with_no_originations(self) -> None:
        svc = reporting()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "a",
                      "principal": 10000
                  }))
        report = svc.generate_report()
        assert report["total_originations"] == 0
        assert report["default_rate"] == 1.0

    def test_handles_non_loan_events_gracefully(self) -> None:
        svc = reporting()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(Event(event_type="user.added", source="test", payload={}))
        report = svc.generate_report()
        assert report["total_originations"] == 0
        assert report["total_defaults"] == 0
