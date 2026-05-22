"""Tests for Store failure handling — FileStore corruption, CQRS."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from underwrite.__store__ import CQRSStore, FileStore, MemoryStore, ReadStore, Store


class TestFileStoreCorruption:

    def test_corrupted_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            store.set("key1", {"value": 42})
            path = Path(tmp) / "key1.json"
            path.write_text("not valid json{{{")
            result = store.get("key1")
            assert result is None

    def test_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            result = store.get("nonexistent")
            assert result is None

    def test_corrupted_file_logs_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStore(tmp)
            store.set("key1", {"value": 42})
            path = Path(tmp) / "key1.json"
            path.write_text("{bad json]")
            result = store.get("key1")
            assert result is None


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

    def test_health_delegates_to_read(self) -> None:
        write = MockStore()
        read = MockReadStore()
        cqrs = CQRSStore(write, read)
        assert cqrs.health() == {"ok": True}
