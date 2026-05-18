"""Automated RBI reporting exports.

Item 16 from production roadmap.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Any

from ulu.infra.logging import logger


@dataclass
class RbiReportRow:
    """Single row in an RBI report."""

    period: str
    metric_name: str
    metric_value: float
    unit: str
    category: str


class RbiReportingService:
    """Generates monthly/quarterly RBI submission reports.

    Supports CSV export; XBRL generation is stubbed pending
    schema alignment with RBI circulars.
    """

    def __init__(self) -> None:
        self._templates: dict[str, list[str]] = {
            "monthly": [
                "total_outstanding_principal",
                "total_delegated_capacity",
                "default_rate",
                "avg_interest_rate",
                "dlg_pool_balance",
            ],
            "quarterly": [
                "total_outstanding_principal",
                "default_rate",
                "npa_ratio",
                "provision_coverage",
                "capital_adequacy",
                "dlg_pool_balance",
            ],
        }

    def generate_report(
        self,
        report_type: str,
        period: str,
        data: dict[str, float],
    ) -> list[RbiReportRow]:
        """Generates report rows from raw data."""
        if report_type not in self._templates:
            raise ValueError(f"unknown report type: {report_type}")
        rows: list[RbiReportRow] = []
        for metric in self._templates[report_type]:
            value = data.get(metric, 0.0)
            rows.append(
                RbiReportRow(
                    period=period,
                    metric_name=metric,
                    metric_value=value,
                    unit="INR" if "balance" in metric or "principal" in metric else "pct",
                    category=report_type,
                )
            )
        logger.info("rbi_report_generated", report_type=report_type, period=period, rows=len(rows))
        return rows

    def export_csv(self, rows: list[RbiReportRow]) -> str:
        """Exports report rows as CSV."""
        if not rows:
            return ""
        buffer = StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["period", "metric_name", "metric_value", "unit", "category"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "period": row.period,
                    "metric_name": row.metric_name,
                    "metric_value": row.metric_value,
                    "unit": row.unit,
                    "category": row.category,
                }
            )
        return buffer.getvalue()

    def export_xbrl_stub(self, rows: list[RbiReportRow]) -> dict[str, Any]:
        """Stub for XBRL generation pending RBI schema alignment."""
        logger.info("rbi_xbrl_stub", rows=len(rows))
        return {
            "status": "stub",
            "note": "XBRL generation requires RBI taxonomy and schema alignment",
            "row_count": len(rows),
        }
