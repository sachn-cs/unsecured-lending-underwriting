"""Tests for AuditService — append-only event ledger.

Tests verify behavior through public interfaces only:
  - ledger property (returns copy of records)
  - events_by_type() method
  - save/load JSONL round-trip
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event
from underwrite.services.audit.service import AuditService


def audit() -> AuditService:
    return AuditService(service_id="audit")


def audit_capped() -> AuditService:
    return AuditService(service_id="audit", max_ledger=5)


class TestAuditService:

    def test_records_all_event_types(self) -> None:
        svc = audit()
        svc.handle(
            Event(event_type="seed.added",
                  source="test",
                  payload={"user": "bank"}))
        svc.handle(
            Event(event_type="loan.originated",
                  source="test",
                  payload={"borrower": "a"}))
        assert len(svc.ledger) == 2

    def test_ledger_records_all_fields(self) -> None:
        svc = audit()
        svc.handle(
            Event(event_type="test.event",
                  source="src",
                  payload={"k": "v"},
                  correlation_id="corr-1"))
        rec = svc.ledger[0]
        assert rec["event_type"] == "test.event"
        assert rec["source"] == "src"
        assert rec["payload"] == {"k": "v"}
        assert rec["correlation_id"] == "corr-1"
        assert rec["seq"] == 1
        assert "recorded_at" in rec

    def test_ledger_does_not_expose_internal_list(self) -> None:
        svc = audit()
        svc.handle(Event(event_type="a", source="s"))
        ledger = svc.ledger
        ledger.clear()
        assert len(svc.ledger) == 1

    def test_events_by_type_filters_correctly(self) -> None:
        svc = audit()
        for i in range(5):
            svc.handle(Event(event_type="t1", source="s", payload={"i": i}))
        svc.handle(Event(event_type="t2", source="s", payload={}))
        assert len(svc.events_by_type("t1")) == 5
        assert len(svc.events_by_type("t2")) == 1
        assert len(svc.events_by_type("nonexistent")) == 0

    def test_sequential_numbering(self) -> None:
        svc = audit()
        for _i in range(10):
            svc.handle(Event(event_type="ev", source="s"))
        seqs = [r["seq"] for r in svc.ledger]
        assert seqs == list(range(1, 11))

    def test_save_and_load_jsonl_round_trip(self, tmp_path: Any) -> None:
        svc = audit()
        svc.handle(Event(event_type="e1", source="s", payload={"x": 1}))
        svc.handle(Event(event_type="e2", source="s", payload={"y": 2}))
        path = str(tmp_path / "audit.jsonl")
        svc.save_jsonl(path)
        loaded = audit()
        loaded.load_jsonl(path)
        assert len(loaded.ledger) == 2
        assert loaded.ledger[0]["event_type"] == "e1"
        assert loaded.ledger[1]["event_type"] == "e2"

    def test_empty_ledger_save_and_load(self, tmp_path: Any) -> None:
        svc = audit()
        path = str(tmp_path / "empty.jsonl")
        svc.save_jsonl(path)
        loaded = audit()
        loaded.load_jsonl(path)
        assert len(loaded.ledger) == 0

    def test_load_corrupted_jsonl_skips_bad_lines(self, tmp_path: Any) -> None:
        path = str(tmp_path / "bad.jsonl")
        with open(path, "w") as f:
            f.write("{invalid json\n")
        svc = audit()
        svc.load_jsonl(path)
        assert len(svc.ledger) == 0

    def test_load_mixed_jsonl_skips_bad_lines(self, tmp_path: Any) -> None:
        path = str(tmp_path / "mixed.jsonl")
        with open(path, "w") as f:
            f.write('{"good": true}\ncorrupted\n{"also": "ok"}\n')
        svc = audit()
        svc.load_jsonl(path)
        assert len(svc.ledger) == 2
        assert svc.ledger[0] == {"good": True}
        assert svc.ledger[1] == {"also": "ok"}

    def test_multiple_records_have_unique_seqs(self) -> None:
        svc = audit()
        seqs = set()
        for _i in range(100):
            svc.handle(Event(event_type="ev", source="s"))
            seqs.add(svc.ledger[-1]["seq"])
        assert len(seqs) == 100

    def test_capped_ledger_evicts_oldest(self) -> None:
        svc = audit_capped()
        for i in range(10):
            svc.handle(Event(event_type="ev", source="s", payload={"i": i}))
        assert len(svc.ledger) == 5
        assert svc.ledger[0]["payload"] == {"i": 5}
        assert svc.ledger[-1]["payload"] == {"i": 9}

    def test_export_noop_without_url(self) -> None:
        svc = AuditService(service_id="audit")
        svc.handle(Event(event_type="ev", source="s"))
        svc.export()  # should not raise

    def test_export_s3_calls_boto3(self) -> None:
        from unittest.mock import MagicMock, patch
        put_called = [False]

        mock_s3 = MagicMock()
        mock_s3.put_object = MagicMock(
            side_effect=lambda **kw: put_called.__setitem__(0, True))

        mock_boto3_mod = MagicMock()
        mock_boto3_mod.client = MagicMock(return_value=mock_s3)

        with patch.dict("sys.modules", {"boto3": mock_boto3_mod}):
            if "underwrite.services.audit.service" in __import__("sys").modules:
                __import__("sys").modules.pop(
                    "underwrite.services.audit.service", None)
            from underwrite.services.audit.service import AuditService as AuditSvc2
            svc2 = AuditSvc2(service_id="audit",
                             export_url="s3://bucket/path.jsonl")
            svc2.handle(Event(event_type="ev", source="s"))
            svc2.export()
        assert put_called[0]

    def test_export_gcs_noop_without_library(self) -> None:
        svc = AuditService(service_id="audit",
                           export_url="gs://bucket/path.jsonl")
        svc.handle(Event(event_type="ev", source="s"))
        svc.export()  # should log warning, not raise
