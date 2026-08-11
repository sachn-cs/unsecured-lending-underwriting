# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Persistence abstraction for state and log storage.

The platform runs on a single backend: SQLite (stdlib ``sqlite3``).
Pass ``":memory:"`` as the path for an in-process database; pass a
file path for a persistent one. The ``Store`` façade accepts
``type="sqlite"`` and a ``path`` keyword for legacy call sites.

Public API:

    Sqlite(path="./store.db")          # file-backed
    Sqlite(path=":memory:")            # in-process
    Store(type="sqlite", path="…")     # façade: delegates to Sqlite
"""

from __future__ import annotations

__all__ = [
    "Sqlite",
    "Store",
    "StoreBackend",
]

import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from underwrite.exceptions import StoreError
from underwrite.logger import logger

DEFAULT_BUSY_TIMEOUT_SECONDS: float = 30.0

CORRUPTION_ERRNOS: frozenset[str] = frozenset({"database disk image is malformed", "file is not a database"})


class Connection(Protocol):
    """Minimal protocol for a DB-API 2.0 connection."""

    def cursor(self) -> Any: ...

    @property
    def closed(self) -> bool: ...

    def close(self) -> None: ...


class StoreBackend(Protocol):
    """Minimal contract every concrete backend satisfies."""

    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def delete(self, key: str) -> bool: ...
    def exists(self, key: str) -> bool: ...
    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]: ...
    def shutdown(self) -> None: ...
    def health(self) -> dict[str, Any]: ...
    def migrate(self, plan: Any) -> None: ...


class Sqlite:
    """SQLite-backed store using stdlib ``sqlite3``.

    A *path* of ``":memory:"`` selects a private in-process database;
    any other path is treated as a file location (parent directories
    are created on first use). A single ``threading.Lock`` serialises
    write transactions; reads may run concurrently but the connection
    is closed at the end of every operation so ``check_same_thread``
    is irrelevant.

    PRAGMAs applied per connection:
      - ``journal_mode=WAL`` so readers do not block writers
      - ``synchronous=NORMAL`` (durable enough for WAL)
      - ``foreign_keys=ON``
      - ``busy_timeout`` defaults to 30 s to ride out transient locks
    """

    def __init__(
        self,
        path: str = ":memory:",
        busy_timeout: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
    ) -> None:
        self.path: Path = Path(path)
        self.busy_timeout: float = busy_timeout
        self.lock: threading.Lock = threading.Lock()
        self._shared_conn: sqlite3.Connection | None = None
        self._init_error: str | None = None
        if self.path_str() != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._init_schema()
        except sqlite3.DatabaseError as exc:
            self._init_error = str(exc)
            logger.warning("sqlite store init failed for {}: {}", self.path_str(), exc)

    def path_str(self) -> str:
        return str(self.path)

    def is_memory(self) -> bool:
        return self.path_str() == ":memory:"

    def _connect(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(
            self.path_str(),
            timeout=self.busy_timeout,
            check_same_thread=False,
        )
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout * 1000)}")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        if self.is_memory():
            self._shared_conn = self._connect()
            self._shared_conn.execute("CREATE TABLE IF NOT EXISTS store (  key TEXT PRIMARY KEY,  value BLOB NOT NULL)")
            self._shared_conn.commit()
            return
        conn = self._connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS store (  key TEXT PRIMARY KEY,  value BLOB NOT NULL)")
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _txn(self) -> Generator[sqlite3.Connection, None, None]:
        shared = self._shared_conn is not None
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except sqlite3.DatabaseError as exc:
            try:
                conn.rollback()
            except sqlite3.DatabaseError:
                pass
            self._raise_for_corruption(exc)
            raise StoreError(f"sqlite operation failed: {exc}") from None
        except Exception:
            try:
                conn.rollback()
            except sqlite3.DatabaseError:
                pass
            raise
        finally:
            if not shared:
                conn.close()

    @staticmethod
    def _raise_for_corruption(exc: BaseException) -> None:
        msg = str(exc).lower()
        if any(needle in msg for needle in CORRUPTION_ERRNOS):
            raise StoreError(f"sqlite database is corrupted: {exc}") from None

    def get(self, key: str) -> Any | None:
        with self.lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT value FROM store WHERE key = ?", (key,)).fetchone()
            except sqlite3.DatabaseError as exc:
                self._raise_for_corruption(exc)
                raise StoreError(f"sqlite read failed: {exc}") from None
            finally:
                if self._shared_conn is None:
                    conn.close()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            logger.warning("failed to decode sqlite value for {}", key)
            return None

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, default=str).encode("utf-8")
        with self.lock:
            with self._txn() as conn:
                conn.execute(
                    "INSERT INTO store (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, encoded),
                )

    def delete(self, key: str) -> bool:
        with self.lock:
            with self._txn() as conn:
                cur = conn.execute("DELETE FROM store WHERE key = ?", (key,))
                return cur.rowcount > 0

    def exists(self, key: str) -> bool:
        with self.lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT 1 FROM store WHERE key = ?", (key,)).fetchone()
            except sqlite3.DatabaseError as exc:
                self._raise_for_corruption(exc)
                raise StoreError(f"sqlite read failed: {exc}") from None
            finally:
                if self._shared_conn is None:
                    conn.close()
        return row is not None

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        with self.lock:
            conn = self._connect()
            try:
                all_keys = [r[0] for r in conn.execute("SELECT key FROM store ORDER BY key").fetchall()]
            except sqlite3.DatabaseError as exc:
                self._raise_for_corruption(exc)
                raise StoreError(f"sqlite read failed: {exc}") from None
            finally:
                if self._shared_conn is None:
                    conn.close()
        if pattern is not None:
            needle = pattern.rstrip("*")
            all_keys = [k for k in all_keys if needle in k]
        if offset > 0:
            all_keys = all_keys[offset:]
        if limit > 0:
            all_keys = all_keys[:limit]
        return all_keys

    def shutdown(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        try:
            with self.lock:
                conn = self._connect()
                try:
                    conn.execute("SELECT 1").fetchone()
                finally:
                    if self._shared_conn is None:
                        conn.close()
        except Exception as exc:
            return {"ok": False, "detail": str(exc), "path": self.path_str()}
        return {"ok": True, "path": self.path_str()}

    def migrate(self, plan: Any) -> None:
        if plan is None:
            return
        from underwrite.migrate import MigrationPlan

        if not isinstance(plan, MigrationPlan):
            raise StoreError(f"migrate() expects MigrationPlan, got {type(plan).__name__}")
        shared = self._shared_conn is not None
        conn = self._connect()
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migrations'")
            if cur.fetchone() is None:
                conn.execute(
                    "CREATE TABLE migrations ("
                    "  version INTEGER PRIMARY KEY,"
                    "  description TEXT NOT NULL,"
                    "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                    ")"
                )
            conn.commit()
        finally:
            if not shared:
                conn.close()
        conn = self._connect()
        try:
            applied_rows = conn.execute("SELECT version FROM migrations").fetchall()
            applied = {int(r[0]) for r in applied_rows}
            for migration in plan.pending(applied):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for stmt in migration.statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR IGNORE INTO migrations (version, description) VALUES (?, ?)",
                        (migration.version, migration.description),
                    )
                    conn.commit()
                    logger.info("migration v{} applied: {}", migration.version, migration.description)
                except Exception as exc:
                    conn.rollback()
                    from underwrite.exceptions import MigrationError

                    raise MigrationError(
                        f"migration v{migration.version} ({migration.description}) failed: {exc}"
                    ) from exc
        finally:
            if not shared:
                conn.close()


class Store:
    """Façade that delegates to ``Sqlite``.

    The legacy ``type="memory"`` selector is preserved for existing
    call sites: it returns ``Sqlite(":memory:")``. The only other
    accepted type is ``"sqlite"``.
    """

    SQLITE = "sqlite"
    MEMORY = "memory"

    def __init__(
        self,
        type: str = SQLITE,
        *,
        path: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.type: str = type
        kwargs.pop("data_dir", None)
        if type == self.SQLITE:
            db_path: str = path if path is not None else ":memory:"
            self.implementation: StoreBackend = Sqlite(path=db_path, **kwargs)
        elif type == self.MEMORY:
            self.implementation = Sqlite(path=":memory:", **kwargs)
        else:
            raise ValueError(f"unknown store type: {type!r}; expected 'sqlite' or 'memory'")

    def get(self, key: str) -> Any | None:
        return self.implementation.get(key)

    def set(self, key: str, value: Any) -> None:
        self.implementation.set(key, value)

    def delete(self, key: str) -> bool:
        return self.implementation.delete(key)

    def exists(self, key: str) -> bool:
        return self.implementation.exists(key)

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        return self.implementation.keys(pattern=pattern, limit=limit, offset=offset)

    def shutdown(self) -> None:
        self.implementation.shutdown()

    def health(self) -> dict[str, Any]:
        return self.implementation.health()

    def migrate(self, plan: Any) -> None:
        self.implementation.migrate(plan)
