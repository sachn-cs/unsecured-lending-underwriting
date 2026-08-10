# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Persistence abstraction for state and log storage.

Composition over inheritance: InMemory, Disk, and Sqlite are
standalone backend classes (no ABC). The Store façade wraps one
backend and delegates every method to it.

Public API:

    InMemory()                  # in-process dict
    Disk(data_dir="./data")      # JSON-per-file
    Sqlite(path="./store.db")    # stdlib sqlite3
    Store(type="memory")         # façade: picks a backend
    Store(type="disk", data_dir="…")
    Store(type="sqlite", path="…")
"""

from __future__ import annotations

__all__ = [
    "CQRSStore",
    "Disk",
    "InMemory",
    "Sqlite",
    "ReadStore",
    "Store",
    "StoreBackend",
]

import concurrent.futures
import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from underwrite.circuit import CircuitBreaker
from underwrite.exceptions import StoreError
from underwrite.logger import logger

FILE_TIMEOUT_MSG: str = "store operation timed out after %.1fs on %s"


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


class InMemory:
    """Thread-safe in-memory store. Data is lost on process exit.

    Bounded by *max_entries* — when the limit is reached the oldest
    entries (by insertion order) are evicted to stay within budget.
    """

    def __init__(self, max_entries: int = 0) -> None:
        self.lock: threading.Lock = threading.Lock()
        self.data: dict[str, Any] = {}
        self.max_entries: int = max_entries
        self.insertion_order: list[str] = []  # insertion-order tracking for eviction

    def get(self, key: str) -> Any | None:
        with self.lock:
            return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            is_new: bool = key not in self.data
            if is_new and self.max_entries > 0:
                while len(self.insertion_order) >= self.max_entries:
                    evicted = self.insertion_order.pop(0)
                    self.data.pop(evicted, None)
                self.insertion_order.append(key)
            self.data[key] = value

    def delete(self, key: str) -> bool:
        with self.lock:
            return self.data.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        with self.lock:
            return key in self.data

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        with self.lock:
            all_keys = [k for k in self.data if pattern is None or pattern.rstrip("*") in k]
            if offset > 0:
                all_keys = all_keys[offset:]
            if limit > 0:
                all_keys = all_keys[:limit]
            return all_keys

    def shutdown(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {"ok": True}

    def migrate(self, plan: Any) -> None:
        return None


class Disk:
    """Filesystem-backed store. Each key maps to a JSON file under *data_dir*."""

    def __init__(
        self,
        data_dir: str = "./data",
        operation_timeout: float = 0.0,
        use_circuit_breaker: bool = False,
        failure_threshold: int = 3,
        fsync: bool = True,
        metrics_collector: Any | None = None,
    ) -> None:
        self.data_dir: Path = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock: threading.Lock = threading.Lock()
        self.operation_timeout: float = operation_timeout
        self.executor: concurrent.futures.ThreadPoolExecutor | None = (
            concurrent.futures.ThreadPoolExecutor(max_workers=1) if operation_timeout > 0 else None
        )
        self.circuit: CircuitBreaker | None = (
            CircuitBreaker(failure_threshold=failure_threshold, recovery_timeout=30.0, name="disk")
            if use_circuit_breaker
            else None
        )
        self.fsync: bool = fsync
        self.metrics: Any | None = metrics_collector

    def shutdown(self, wait: bool = True) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=wait)
            self.executor = None

    def __timeout(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        if self.executor is None:
            return fn(*args, **kwargs)
        fut = self.executor.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=self.operation_timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(FILE_TIMEOUT_MSG % (self.operation_timeout, fn.__name__)) from None

    def __circuit_call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        if self.circuit is None:
            return fn(*args, **kwargs)
        return self.circuit.call(fn, *args, **kwargs)

    def get(self, key: str) -> Any | None:
        def _read() -> Any | None:
            path = self.__path(key)
            if not path.exists():
                return None
            try:
                with open(path) as f:
                    return json.load(f)
            except OSError as exc:
                logger.warning("failed to read store key {}: {}", key, exc)
                if self.metrics is not None and hasattr(self.metrics, "increment"):
                    self.metrics.increment("store.io_error")
                raise StoreError(f"io error reading store key {key!r}: {exc}") from None
            except ValueError as exc:
                logger.warning("failed to read store key {}: {}", key, exc)
                if self.metrics is not None and hasattr(self.metrics, "increment"):
                    self.metrics.increment("store.corruption")
                raise StoreError(f"corrupted store file for {key!r}: {exc}") from None

        try:
            return self.__timeout(_read) if self.executor else self.__circuit_call(_read)
        except TimeoutError:
            return None

    def set(self, key: str, value: Any) -> None:
        def _write() -> None:
            path = self.__path(key)
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                with open(tmp, "w") as f:
                    json.dump(value, f, default=str)
                    if self.fsync:
                        f.flush()
                        import os as _os

                        _os.fsync(f.fileno())
                tmp.replace(path)
            except OSError:
                logger.exception("failed to write store key {}", key)

        if self.executor:
            self.__timeout(_write)
        else:
            self.__circuit_call(_write)

    def delete(self, key: str) -> bool:
        def _delete() -> bool:
            path = self.__path(key)
            if path.exists():
                path.unlink()
                return True
            return False

        if self.executor:
            return bool(self.__timeout(_delete))
        return bool(self.__circuit_call(_delete))

    def exists(self, key: str) -> bool:
        return self.__path(key).exists()

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        def _list() -> list[str]:
            out: list[str] = []
            for child in self.data_dir.iterdir():
                if child.suffix == ".tmp":
                    continue
                name = child.name
                if pattern is None or pattern.rstrip("*") in name:
                    out.append(name)
            return out

        result = self.__timeout(_list) if self.executor else self.__circuit_call(_list)
        result.sort()
        if offset > 0:
            result = result[offset:]
        if limit > 0:
            result = result[:limit]
        return result

    def __path(self, key: str) -> Path:
        if not key or ".." in key or key.startswith("/") or key.startswith("\\"):
            raise StoreError(f"invalid store key: {key!r}")
        safe = key.replace("/", "_").replace("\\", "_")
        # Verify resolved path stays inside data_dir
        candidate = (self.data_dir / safe).resolve()
        if not str(candidate).startswith(str(self.data_dir.resolve())):
            raise StoreError(f"store key {key!r} escapes data_dir")
        return candidate

    def health(self) -> dict[str, Any]:
        return {"ok": True, "data_dir": str(self.data_dir)}

    def migrate(self, plan: Any) -> None:
        return None


class Sqlite:
    """SQLite-backed store using stdlib sqlite3.

    Single file at *path*. Thread-safe via per-call connection.
    """

    def __init__(self, path: str = "./store.db") -> None:
        self.path: Path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock: threading.Lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS store (  key TEXT PRIMARY KEY,  value BLOB NOT NULL)")
            conn.commit()

    @contextmanager
    def _txn(self) -> Generator[sqlite3.Connection, None, None]:
        with self.lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def get(self, key: str) -> Any | None:
        with self._txn() as conn:
            row = conn.execute("SELECT value FROM store WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            try:
                return json.loads(row[0])
            except (ValueError, TypeError):
                logger.warning("failed to decode sqlite value for {}", key)
                return None

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, default=str).encode("utf-8")
        with self._txn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO store (key, value) VALUES (?, ?)",
                (key, encoded),
            )

    def delete(self, key: str) -> bool:
        with self._txn() as conn:
            cur = conn.execute("DELETE FROM store WHERE key = ?", (key,))
            return cur.rowcount > 0

    def exists(self, key: str) -> bool:
        with self._txn() as conn:
            row = conn.execute("SELECT 1 FROM store WHERE key = ?", (key,)).fetchone()
            return row is not None

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        with self._txn() as conn:
            all_keys = [r[0] for r in conn.execute("SELECT key FROM store ORDER BY key").fetchall()]
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
        return {"ok": True, "path": str(self.path)}

    def migrate(self, plan: Any) -> None:
        return None


class Store:
    """Façade that picks one of InMemory/Disk/Sqlite based on *type*.

    Composition, not inheritance: every method delegates to the
    configured backend instance stored as ``self.implementation``.
    """

    MEMORY = "memory"
    DISK = "disk"
    SQLITE = "sqlite"

    def __init__(
        self,
        type: str = MEMORY,
        *,
        path: str | None = None,
        max_entries: int = 0,
        **kwargs: Any,
    ) -> None:
        self.type: str = type
        if type == self.MEMORY:
            self.implementation: StoreBackend = InMemory(max_entries=max_entries)
        elif type == self.DISK:
            kwargs.pop("data_dir", None)
            data_dir: str = path if path is not None else "./data"
            self.implementation = Disk(data_dir=data_dir, **kwargs)
        elif type == self.SQLITE:
            kwargs.pop("path", None)
            db_path: str = path if path is not None else "./store.db"
            self.implementation = Sqlite(path=db_path, **kwargs)
        else:
            raise ValueError(f"unknown store type: {type!r}")

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


class ReadStore:
    """Read-only store for CQRS query side.

    Same backend can be passed in read-only mode; writes raise StoreError.
    """

    def __init__(self, backend: StoreBackend) -> None:
        self.implementation: StoreBackend = backend

    def get(self, key: str) -> Any | None:
        return self.implementation.get(key)

    def exists(self, key: str) -> bool:
        return self.implementation.exists(key)

    def delete(self, key: str) -> bool:
        raise StoreError("ReadStore is read-only")

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        return self.implementation.keys(pattern=pattern, limit=limit, offset=offset)

    def shutdown(self) -> None:
        self.implementation.shutdown()

    def health(self) -> dict[str, Any]:
        return self.implementation.health()


class CQRSStore(Store):
    """A store that delegates writes to write-store and reads from read-store.

    For now it is a thin wrapper around a single Store; future versions
    can split the read and write paths into separate backends.
    """

    def __init__(self, write_store: Store, read_store: ReadStore | None = None) -> None:
        self.write_store: Store = write_store
        self.read_store: ReadStore = read_store or ReadStore(write_store)

    def get(self, key: str) -> Any | None:
        return self.read_store.get(key)

    def set(self, key: str, value: Any) -> None:
        self.write_store.set(key, value)

    def delete(self, key: str) -> bool:
        return self.write_store.delete(key)

    def exists(self, key: str) -> bool:
        return self.read_store.exists(key)

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        return self.write_store.keys(pattern=pattern, limit=limit, offset=offset)

    def shutdown(self) -> None:
        self.write_store.shutdown()
        self.read_store.shutdown()

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": True}
        try:
            result["write_store"] = self.write_store.health()
        except Exception as exc:
            result["write_store"] = {"ok": False, "error": str(exc)}
            result["ok"] = False
        try:
            result["read_store"] = self.read_store.health()
        except Exception as exc:
            result["read_store"] = {"ok": False, "error": str(exc)}
            result["ok"] = False
        return result

    def migrate(self, plan: Any) -> None:
        self.write_store.migrate(plan)
