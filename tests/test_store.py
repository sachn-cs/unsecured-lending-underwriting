# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for the Sqlite store backend — CRUD, pagination, corruption handling."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from underwrite.exceptions import StoreError
from underwrite.store import Sqlite, Store


class TestSqliteMemory:
    def test_get_missing(self) -> None:
        store = Sqlite(":memory:")
        assert store.get("nonexistent") is None

    def test_set_and_get(self) -> None:
        store = Sqlite(":memory:")
        store.set("k", "v")
        assert store.get("k") == "v"

    def test_set_and_get_nested(self) -> None:
        store = Sqlite(":memory:")
        store.set("k", {"a": [1, 2, 3]})
        assert store.get("k") == {"a": [1, 2, 3]}

    def test_delete_existing(self) -> None:
        store = Sqlite(":memory:")
        store.set("k", "v")
        assert store.delete("k") is True
        assert store.get("k") is None

    def test_delete_missing(self) -> None:
        store = Sqlite(":memory:")
        assert store.delete("nonexistent") is False

    def test_exists(self) -> None:
        store = Sqlite(":memory:")
        store.set("k", "v")
        assert store.exists("k") is True
        assert store.exists("missing") is False

    def test_keys(self) -> None:
        store = Sqlite(":memory:")
        store.set("a", 1)
        store.set("b", 2)
        assert set(store.keys()) == {"a", "b"}

    def test_keys_with_pattern(self) -> None:
        store = Sqlite(":memory:")
        store.set("foo.bar", 1)
        store.set("foo.baz", 2)
        store.set("other", 3)
        keys = store.keys("foo.")
        assert "foo.bar" in keys
        assert "foo.baz" in keys
        assert "other" not in keys

    def test_health_ok(self) -> None:
        store = Sqlite(":memory:")
        h = store.health()
        assert h["ok"] is True

    def test_thread_safety(self) -> None:
        import threading

        store = Sqlite(":memory:")
        errors: list[Exception] = []

        def writer(i: int) -> None:
            try:
                for j in range(50):
                    store.set(f"key:{i}:{j}", j)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors


class TestSqliteFile:
    def test_persistence(self, tmp_path: Path) -> None:
        path = str(tmp_path / "store.db")
        s1 = Sqlite(path=path)
        s1.set("user:alice", {"credit": 100.0})
        s1.set("user:bob", {"credit": 50.0})
        s2 = Sqlite(path=path)
        assert s2.get("user:alice") == {"credit": 100.0}
        assert s2.get("user:bob") == {"credit": 50.0}

    def test_keys(self, tmp_path: Path) -> None:
        path = str(tmp_path / "store.db")
        s = Sqlite(path=path)
        s.set("a:x", 1)
        s.set("a:y", 2)
        s.set("b:z", 3)
        assert "b:z" not in s.keys("a:")
        assert "a:x" in s.keys("a:")

    def test_keys_pagination(self, tmp_path: Path) -> None:
        path = str(tmp_path / "store.db")
        s = Sqlite(path=path)
        for i in range(10):
            s.set(f"k:{i}", i)
        all_keys = s.keys()
        assert len(all_keys) == 10
        assert len(s.keys(limit=3)) == 3
        assert len(s.keys(limit=3, offset=5)) == 3

    def test_default_path_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "subdir" / "store.db"
        s = Sqlite(path=str(nested))
        s.set("k", "v")
        assert nested.exists()


class TestSqliteCorruption:
    def test_corrupted_file_raises_store_error(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.db"
        path.write_bytes(b"not a sqlite database at all")
        with pytest.raises((StoreError, sqlite3.DatabaseError)):
            Sqlite(path=str(path)).get("k")

    def test_health_returns_error_on_corrupted_file(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.db"
        path.write_bytes(b"definitely not sqlite")
        s = Sqlite(path=str(path))
        h = s.health()
        assert h["ok"] is False
        assert "detail" in h

    def test_health_records_path(self) -> None:
        s = Sqlite(path=":memory:")
        h = s.health()
        assert h["path"] == ":memory:"


class TestStoreFacade:
    def test_sqlite_default(self) -> None:
        s = Store(type="sqlite", path=":memory:")
        s.set("k", "v")
        assert s.get("k") == "v"

    def test_memory_alias(self) -> None:
        s = Store(type="memory")
        s.set("k", "v")
        assert s.get("k") == "v"

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown store type"):
            Store(type="dynamodb")

    def test_default_backend_is_sqlite(self) -> None:
        s = Store()
        s.set("k", "v")
        assert s.get("k") == "v"


class TestSqliteMigration:
    def test_default_plan_applies(self) -> None:
        from underwrite.migrate import default_plan

        s = Sqlite(path=":memory:")
        s.migrate(default_plan())
        s2 = Sqlite(path=":memory:")
        s2.migrate(default_plan())
        assert s.health()["ok"] is True

    def test_idempotent_migration(self, tmp_path: Path) -> None:
        from underwrite.migrate import default_plan

        path = str(tmp_path / "store.db")
        s = Sqlite(path=path)
        s.migrate(default_plan())
        s.migrate(default_plan())
        conn = sqlite3.connect(path)
        count = conn.execute("SELECT COUNT(*) FROM migrations").fetchone()[0]
        conn.close()
        assert count == len(default_plan().migrations)
