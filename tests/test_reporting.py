# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — regulatory report generation.

Tests verify behavior through the public generate_report() method.
"""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.reporting import Handler
from underwrite.services.reporting import Handler as ReportingHandler
from underwrite.store import InMemory


def reporting() -> Handler:
    return ReportingHandler(name="reporting", bus=LocalBus(), store=InMemory())


class TestReportingService:
    def test_records_events(self) -> None:
        svc = reporting()
        svc.handle(
            Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={"borrower": "alice", "principal": 10000})
        )
        svc.handle(
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "alice", "principal": 10000})
        )
        report = svc.generate_report()
        assert report["total_originations"] == 1
        assert report["total_defaults"] == 1

    def test_portfolio_summary_counts(self) -> None:
        svc = reporting()
        for i in range(10):
            svc.handle(
                Message(
                    event_type=Type.LOAN_ORIGINATED,
                    source="test",
                    payload={"borrower": f"b{i}", "principal": 10000},
                )
            )
        for i in range(3):
            svc.handle(
                Message(
                    event_type=Type.DEFAULT_OCCURRED,
                    source="test",
                    payload={"borrower": f"b{i}", "principal": 10000},
                )
            )
        report = svc.generate_report()
        assert report["total_originations"] == 10
        assert report["total_defaults"] == 3
        assert report["default_rate"] == 0.3

    def test_total_principal_originated(self) -> None:
        svc = reporting()
        svc.handle(
            Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={"borrower": "a", "principal": 50000})
        )
        svc.handle(
            Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={"borrower": "b", "principal": 150000})
        )
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
            Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={"borrower": "a", "principal": 10000})
        )
        report = svc.generate_report()
        assert report["total_originations"] == 0
        assert report["default_rate"] == 1.0

    def test_handles_non_loan_events_gracefully(self) -> None:
        svc = reporting()
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        svc.handle(Message(event_type="user.added", source="test", payload={}))
        report = svc.generate_report()
        assert report["total_originations"] == 0
        assert report["total_defaults"] == 0


class TestReportingNpaReport:
    def test_generate_npa_report_defaults(self) -> None:
        svc = reporting()
        report = svc.generate_npa_report()
        assert report["report_type"] == "npa_detailed"
        assert report["npa_principal"] == 0.0
        assert report["npa_ratio"] == 0.0
        assert report["total_provisioning"] == 0.0
        assert report["provisioning_coverage_ratio"] == 0.0

    def test_tracks_npa_bucket_changes(self) -> None:
        svc = reporting()
        svc.handle(
            Message(
                event_type=Type.NPA_BUCKET_CHANGED,
                source="npa",
                payload={"borrower": "b1", "bucket": "substandard"},
            )
        )
        report = svc.generate_npa_report()
        assert report["bucket_counts"]["substandard"] == 1
        assert report["bucket_counts"]["standard"] == 0

    def test_tracks_provisioning_computed(self) -> None:
        svc = reporting()
        svc.handle(
            Message(
                event_type=Type.PROVISIONING_COMPUTED,
                source="npa",
                payload={
                    "borrower": "b2",
                    "bucket": "substandard",
                    "outstanding": 100000.0,
                    "provisioning_rate": 0.15,
                    "provisioning_amount": 15000.0,
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.PROVISIONING_COMPUTED,
                source="npa",
                payload={
                    "borrower": "b3",
                    "bucket": "loss",
                    "outstanding": 50000.0,
                    "provisioning_rate": 1.0,
                    "provisioning_amount": 50000.0,
                },
            )
        )
        report = svc.generate_npa_report()
        assert report["total_provisioning"] == 65000.0
        assert report["bucket_principals"]["loss"] == 50000.0
        assert report["npa_principal"] == 150000.0

    def test_provisioning_coverage_ratio(self) -> None:
        svc = reporting()
        svc.handle(
            Message(
                event_type=Type.NPA_BUCKET_CHANGED,
                source="npa",
                payload={"borrower": "b4", "bucket": "substandard"},
            )
        )
        svc.handle(
            Message(
                event_type=Type.PROVISIONING_COMPUTED,
                source="npa",
                payload={
                    "borrower": "b4",
                    "bucket": "substandard",
                    "outstanding": 100000.0,
                    "provisioning_rate": 0.15,
                    "provisioning_amount": 15000.0,
                },
            )
        )
        report = svc.generate_npa_report()
        assert report["provisioning_coverage_ratio"] == 0.15

    def test_npa_ratio(self) -> None:
        """RBI NPA ratio = NPA outstanding / total outstanding (per bucket)."""
        svc = reporting()
        svc.handle(
            Message(
                event_type=Type.PROVISIONING_COMPUTED,
                source="npa",
                payload={
                    "borrower": "standard_a",
                    "bucket": "standard",
                    "outstanding": 450000.0,
                    "provisioning_rate": 0.0025,
                    "provisioning_amount": 1125.0,
                },
            )
        )
        svc.handle(
            Message(
                event_type=Type.PROVISIONING_COMPUTED,
                source="npa",
                payload={
                    "borrower": "doubtful_a",
                    "bucket": "doubtful",
                    "outstanding": 50000.0,
                    "provisioning_rate": 0.25,
                    "provisioning_amount": 12500.0,
                },
            )
        )
        report = svc.generate_npa_report()
        # NPA = 50000, outstanding = 500000 → ratio = 0.1
        assert report["npa_principal"] == 50000.0
        assert report["npa_ratio"] == 0.1
