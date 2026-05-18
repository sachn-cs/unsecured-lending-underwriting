"""Data archival for old audit events and NPA records.

Item 11 from production roadmap.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from io import StringIO
from typing import Any

from ulu.infra.logging import logger


@dataclass
class ArchivalRecord:
    """Represents a single record ready for archival."""

    record_id: str
    record_type: str
    payload: dict[str, Any]
    created_at: str


class ArchivalService:
    """Manages archival of expired records to external storage.

    In production this should write to S3, GCS, or Glacier.
    """

    def __init__(self, retention_years: int = 7) -> None:
        self.retention_years = retention_years
        self._archived: list[ArchivalRecord] = []

    def should_archive(self, created_at: str) -> bool:
        """Stub: real implementation would parse timestamp and compare."""
        return False  # archival is time-driven; stub always returns False

    def export_to_jsonl(self, records: list[ArchivalRecord]) -> str:
        """Exports records as newline-delimited JSON."""
        lines = []
        for r in records:
            lines.append(
                json.dumps(
                    {
                        "record_id": r.record_id,
                        "record_type": r.record_type,
                        "payload": r.payload,
                        "created_at": r.created_at,
                    }
                )
            )
        return "\n".join(lines)

    def export_to_csv(self, records: list[ArchivalRecord]) -> str:
        """Exports records as CSV."""
        if not records:
            return ""
        buffer = StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["record_id", "record_type", "created_at", "payload_json"],
        )
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "record_id": r.record_id,
                    "record_type": r.record_type,
                    "created_at": r.created_at,
                    "payload_json": json.dumps(r.payload),
                }
            )
        return buffer.getvalue()

    def archive(self, records: list[ArchivalRecord]) -> dict[str, Any]:
        """Archives records and returns summary."""
        self._archived.extend(records)
        logger.info(
            "records_archived",
            count=len(records),
            retention_years=self.retention_years,
        )
        return {
            "archived_count": len(records),
            "total_archived": len(self._archived),
            "format": "in_memory_stub",
        }

    def list_archived(self) -> list[ArchivalRecord]:
        """Returns all archived records."""
        return list(self._archived)
