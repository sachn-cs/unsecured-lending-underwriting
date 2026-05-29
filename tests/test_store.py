"""Tests for Store failure handling — FileStore corruption, CQRS."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from underwrite.__exceptions__ import StoreError
from underwrite.__metrics__ import MetricsCollector
from underwrite.__store__ import CQRSStore, FileStore, MemoryStore, PostgresStore, ReadStore, Store


class TestFileStoreCorruption:

    def test_corrupted_json_raises_store_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            store.set("key1", {"value": 42})
            path = Path(tmp) / "key1.json"
            path.write_text("not valid json{{{")
            with pytest.raises(StoreError, match="corrupted store file"):
                store.get("key1")

    def test_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            result = store.get("nonexistent")
            assert result is None

    def test_corrupted_file_raises_store_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            store.set("key1", {"value": 42})
            path = Path(tmp) / "key1.json"
            path.write_text("{bad json]")
            with pytest.raises(StoreError, match="corrupted store file"):
                store.get("key1")

    def test_corruption_increments_metric(self) -> None:
        metrics = MetricsCollector()
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp, metrics_collector=metrics)
            store.set("key1", {"value": 42})
            path = Path(tmp) / "key1.json"
            path.write_text("garbage{{{")
            with pytest.raises(StoreError):
                store.get("key1")
        snapshot = metrics.snapshot()
        assert any(
            k.startswith("store.corruption") for k in snapshot["counters"])

    def test_io_error_increments_metric(self) -> None:
        metrics = MetricsCollector()
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp, metrics_collector=metrics)
            store.set("key1", {"value": 42})
            path = Path(tmp) / "key1.json"
            path.chmod(0o200)
            with pytest.raises(StoreError):
                store.get("key1")
        snapshot = metrics.snapshot()
        assert any(k.startswith("store.io_error") for k in snapshot["counters"])


class TestMemoryStore:

    def test_get_missing(self) -> None:
        store = MemoryStore()
        assert store.get("nonexistent") is None

    def test_set_and_get(self) -> None:
        store = MemoryStore()
        store.set("k", "v")
        assert store.get("k") == "v"

    def test_delete_existing(self) -> None:
        store = MemoryStore()
        store.set("k", "v")
        assert store.delete("k") is True
        assert store.get("k") is None

    def test_delete_missing(self) -> None:
        store = MemoryStore()
        assert store.delete("nonexistent") is False

    def test_exists(self) -> None:
        store = MemoryStore()
        store.set("k", "v")
        assert store.exists("k") is True
        assert store.exists("missing") is False

    def test_keys(self) -> None:
        store = MemoryStore()
        store.set("a", 1)
        store.set("b", 2)
        assert set(store.keys()) == {"a", "b"}

    def test_keys_with_pattern(self) -> None:
        store = MemoryStore()
        store.set("foo.bar", 1)
        store.set("foo.baz", 2)
        store.set("other", 3)
        keys = store.keys("foo.*")
        assert "foo.bar" in keys
        assert "foo.baz" in keys
        assert "other" not in keys


class MockStore(Store):

    def __init__(self) -> None:
        self._data: dict = {}

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        return key in self._data

    def keys(self, pattern: str | None = None) -> list:
        return list(self._data.keys())


class MockReadStore(ReadStore):

    def __init__(self) -> None:
        self._data: dict = {}

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def exists(self, key: str) -> bool:
        return key in self._data

    def keys(self, pattern: str | None = None) -> list:
        return list(self._data.keys())


class TestCQRSStore:

    def test_get_from_read_store(self) -> None:
        write = MockStore()
        read = MockReadStore()
        read._data["k"] = "read_val"
        cqrs = CQRSStore(write, read)
        assert cqrs.get("k") == "read_val"

    def test_set_writes_to_write_store(self) -> None:
        write = MockStore()
        read = MockReadStore()
        cqrs = CQRSStore(write, read)
        cqrs.set("k", "write_val")
        assert write._data["k"] == "write_val"
        assert "k" not in read._data

    def test_delete_from_write_store(self) -> None:
        write = MockStore()
        write._data["k"] = "v"
        read = MockReadStore()
        cqrs = CQRSStore(write, read)
        assert cqrs.delete("k") is True
        assert "k" not in write._data

    def test_exists_from_read_store(self) -> None:
        write = MockStore()
        read = MockReadStore()
        read._data["k"] = "v"
        cqrs = CQRSStore(write, read)
        assert cqrs.exists("k") is True

    def test_health_checks_both_stores(self) -> None:
        write = MockStore()
        read = MockReadStore()
        cqrs = CQRSStore(write, read)
        result = cqrs.health()
        assert result["ok"] is True
        assert result["read_store"]["ok"] is True
        assert result["write_store"]["ok"] is True

    def test_health_detects_write_failure(self) -> None:

        class BrokenWriteStore(Store):

            def get(self, key: str) -> None:
                return None

            def set(self, key: str, value: Any) -> None:
                pass

            def delete(self, key: str) -> bool:
                return False

            def exists(self, key: str) -> bool:
                return False

            def keys(self,
                     pattern: str | None = None,
                     limit: int = 0,
                     offset: int = 0) -> list[str]:
                return []

            def health(self) -> dict[str, Any]:
                raise RuntimeError("write store down")

        write = BrokenWriteStore()
        read = MockReadStore()
        cqrs = CQRSStore(write, read)
        result = cqrs.health()
        assert result["ok"] is False
        assert result["write_store"]["ok"] is False


class TestFileStorePathTraversal:

    def test_rejects_dotdot_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            with pytest.raises(StoreError, match="invalid store key"):
                store.get("foo:..:..:etc:passwd")

    def test_rejects_absolute_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            with pytest.raises(StoreError, match="invalid store key"):
                store.get("/etc/passwd")

    def test_rejects_key_resolving_outside_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            with pytest.raises(StoreError):
                store.set("..:etc:passwd", "value")

    def test_normal_key_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            store.set("test:key", {"hello": "world"})
            assert store.get("test:key") == {"hello": "world"}

    def test_keys_with_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            for i in range(10):
                store.set(f"k:{i}", i)
            all_keys = store.keys()
            assert len(all_keys) == 10
            limited = store.keys(limit=3)
            assert len(limited) == 3
            with_offset = store.keys(limit=3, offset=5)
            assert len(with_offset) == 3


class TestPostgresStoreTableName:

    def test_rejects_invalid_table_name(self) -> None:
        with pytest.raises(StoreError, match="invalid table name"):
            PostgresStore(dsn="", table="store; DROP TABLE migrations")

    def test_rejects_table_with_spaces(self) -> None:
        with pytest.raises(StoreError, match="invalid table name"):
            PostgresStore(dsn="", table="my table")

    def test_accepts_valid_table_name(self) -> None:
        store = PostgresStore(dsn="", table="valid_table_1")
        assert store is not None
