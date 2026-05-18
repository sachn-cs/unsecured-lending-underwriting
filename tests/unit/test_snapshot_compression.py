"""Unit tests for snapshot compression."""

from __future__ import annotations

from ulu.infra.snapshot_compression import SnapshotCompressor


class TestSnapshotCompressor:
    def test_roundtrip(self) -> None:
        payload = {"schema_version": 1, "state": {"seeds": ["s1", "s2"], "principal": {"a": 100.0}}}
        compressed = SnapshotCompressor.compress(payload)
        assert isinstance(compressed, bytes)
        assert len(compressed) > 0
        decompressed = SnapshotCompressor.decompress(compressed)
        assert decompressed == payload

    def test_compression_reduces_size(self) -> None:
        import json

        payload = {"data": "x" * 1000}
        compressed = SnapshotCompressor.compress(payload)
        original = json.dumps(payload, sort_keys=True).encode("utf-8")
        assert len(compressed) < len(original)

    def test_empty_dict(self) -> None:
        payload = {}
        compressed = SnapshotCompressor.compress(payload)
        decompressed = SnapshotCompressor.decompress(compressed)
        assert decompressed == {}
