"""Unit tests for data archival service."""

from __future__ import annotations

from ulu.infra.archival import ArchivalRecord, ArchivalService


class TestArchivalService:
    def test_export_to_jsonl(self) -> None:
        svc = ArchivalService()
        records = [
            ArchivalRecord("r1", "audit", {"event": "test"}, "2026-01-01"),
            ArchivalRecord("r2", "npa", {"days": 30}, "2026-01-02"),
        ]
        jsonl = svc.export_to_jsonl(records)
        assert "r1" in jsonl
        assert "r2" in jsonl
        assert jsonl.count("\n") == 1

    def test_export_to_csv(self) -> None:
        svc = ArchivalService()
        records = [
            ArchivalRecord("r1", "audit", {"event": "test"}, "2026-01-01"),
        ]
        csv_text = svc.export_to_csv(records)
        assert "record_id" in csv_text
        assert "r1" in csv_text

    def test_export_empty(self) -> None:
        svc = ArchivalService()
        assert svc.export_to_jsonl([]) == ""
        assert svc.export_to_csv([]) == ""

    def test_archive_and_list(self) -> None:
        svc = ArchivalService()
        records = [ArchivalRecord("r1", "audit", {}, "2026-01-01")]
        result = svc.archive(records)
        assert result["archived_count"] == 1
        assert len(svc.list_archived()) == 1

    def test_should_archive_stub(self) -> None:
        svc = ArchivalService(retention_years=7)
        assert svc.should_archive("2026-01-01") is False
