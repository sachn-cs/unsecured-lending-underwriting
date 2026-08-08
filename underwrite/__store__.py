"""Persistence abstraction for state and log storage.

Supports CQRS — separate read/write stores.  MemoryStore, FileStore,
and PostgresStore with connection pooling and circuit breaker.
"""

from __future__ import annotations

__all__ = [
    "CQRSStore",
    "FileStore",
    "MemoryStore",
    "PostgresStore",
    "ReadStore",
    "Store",
]

import concurrent.futures
import json
import os
import threading
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from underwrite.__circuit__ import CircuitBreaker, RetryPolicy
from underwrite.__exceptions__ import MigrationError, StoreError
from underwrite.__logger__ import logger

if TYPE_CHECKING:
    from underwrite.__migrate__ import MigrationPlan

FILE_TIMEOUT_MSG: str = "store operation timed out after %.1fs on %s"


class Connection(Protocol):
    """Minimal protocol for a DB-API 2.0 connection."""

    def cursor(self) -> Any: ...

    @property
    def closed(self) -> bool: ...

    def close(self) -> None: ...


class Store(ABC):
    """Abstract key-value store.  Thread-safe."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Returns the value for *key*, or ``None``."""

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Persists *value* under *key*."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Removes *key*.  Returns ``True`` if it existed."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Returns ``True`` if *key* is present."""

    @abstractmethod
    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        """Returns all keys, optionally filtered by a simple substring pattern.

        Args:
            pattern: Optional substring pattern to filter keys.
            limit: Max results (0 = unlimited).
            offset: Number of results to skip.
        """

    def shutdown(self) -> None:
        """Release any resources held by the store.  No-op in base class."""
        return None

    def health(self) -> dict[str, Any]:
        """Returns a health-check dict.  Subclasses may override."""
        return {"ok": True}

    def migrate(self, plan: MigrationPlan) -> None:
        """Applies pending schema migrations.  No-op in base class."""
        return None


class ReadStore(ABC):
    """Read-only store for CQRS query side."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Returns the value for *key*, or ``None``."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Returns ``True`` if *key* is present."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Removes *key*.  Returns ``True`` if it existed."""

    @abstractmethod
    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        """Returns all keys, optionally filtered by a substring pattern."""

    def shutdown(self) -> None:
        """Release any resources held by the store.  No-op in base class."""
        return None

    def health(self) -> dict[str, Any]:
        """Returns a health-check dict.  Subclasses may override."""
        return {"ok": True}


class MemoryStore(Store):
    """Thread-safe in-memory store.  Data is lost on process exit.

    Bounded by *max_entries* — when the limit is reached the oldest
    entries (by insertion order) are evicted to stay within budget.
    """

    def __init__(self, max_entries: int = 0) -> None:
        self.__lock: threading.Lock = threading.Lock()
        self.__data: dict[str, Any] = {}
        self.__max_entries: int = max_entries
        self.__keys: list[str] = []  # insertion-order tracking for eviction

    def get(self, key: str) -> Any | None:
        """Returns the value for *key*, or ``None``."""
        with self.__lock:
            return self.__data.get(key)

    def set(self, key: str, value: Any) -> None:
        """Persists *value* under *key*."""
        with self.__lock:
            is_new: bool = key not in self.__data
            if is_new and self.__max_entries > 0:
                while len(self.__keys) >= self.__max_entries:
                    evicted = self.__keys.pop(0)
                    self.__data.pop(evicted, None)
                self.__keys.append(key)
            self.__data[key] = value

    def delete(self, key: str) -> bool:
        """Removes *key*.  Returns ``True`` if it existed."""
        with self.__lock:
            return self.__data.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        """Returns ``True`` if *key* is present."""
        with self.__lock:
            return key in self.__data

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        """Returns all keys, optionally filtered by a substring pattern."""
        with self.__lock:
            all_keys = [k for k in self.__data if pattern is None or pattern.rstrip("*") in k]
            if offset > 0:
                all_keys = all_keys[offset:]
            if limit > 0:
                all_keys = all_keys[:limit]
            return all_keys


class FileStore(Store):
    """Filesystem-backed store.  Each key maps to a JSON file under *data_dir*.

    Args:
        data_dir: Directory for JSON files.
        operation_timeout: Max seconds per I/O operation (0 = no timeout).
        use_circuit_breaker: Enable circuit breaker for this store.
        failure_threshold: Consecutive failures before circuit opens.
    """

    def __init__(
        self,
        data_dir: str = "./data",
        operation_timeout: float = 0.0,
        use_circuit_breaker: bool = False,
        failure_threshold: int = 3,
        fsync: bool = True,
        metrics_collector: Any | None = None,
    ) -> None:
        self.__data_dir: Path = Path(data_dir)
        self.__data_dir.mkdir(parents=True, exist_ok=True)
        self.__lock: threading.Lock = threading.Lock()
        self.__operation_timeout: float = operation_timeout
        self.__executor: concurrent.futures.ThreadPoolExecutor | None = (
            concurrent.futures.ThreadPoolExecutor(max_workers=1) if operation_timeout > 0 else None
        )
        self.__circuit: CircuitBreaker | None = (
            CircuitBreaker(failure_threshold=failure_threshold, recovery_timeout=30.0, name="filestore")
            if use_circuit_breaker
            else None
        )
        self.__fsync: bool = fsync
        self.__metrics: Any | None = metrics_collector

    def shutdown(self, wait: bool = True) -> None:
        """Shuts down the internal thread-pool executor if present."""
        if self.__executor is not None:
            self.__executor.shutdown(wait=wait)
            self.__executor = None

    def __del__(self) -> None:
        try:
            self.shutdown(wait=False)
        except Exception:
            from underwrite.__logger__ import logger

            logger.warning("FileStore.__del__: shutdown failed", exc_info=True)

    def __timeout(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Runs *fn* with the configured timeout via the executor."""
        if self.__executor is None:
            return fn(*args, **kwargs)
        fut = self.__executor.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=self.__operation_timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(FILE_TIMEOUT_MSG % (self.__operation_timeout, fn.__name__)) from None

    def __circuit_call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        if self.__circuit is None:
            return self.__timeout(fn, *args, **kwargs)
        return self.__circuit.call(lambda: self.__timeout(fn, *args, **kwargs))

    def get(self, key: str) -> Any | None:
        """Returns the value for *key*, or ``None`` if key not found.

        Raises:
            StoreError: If the file exists but is corrupted or unreadable.
        """

        def read() -> Any | None:
            path = self.__path(key)
            if not path.exists():
                return None
            try:
                with open(path) as fh:
                    return json.load(fh)
            except json.JSONDecodeError as e:
                logger.exception("corrupted store file %s", path)
                if self.__metrics:
                    self.__metrics.increment("store.corruption", {"path": path.name})
                raise StoreError(f"corrupted store file for key {key}") from e
            except OSError as e:
                logger.exception("I/O error reading store file %s", path)
                if self.__metrics:
                    self.__metrics.increment("store.io_error", {"path": path.name})
                raise StoreError(f"I/O error reading store key {key}") from e

        return self.__circuit_call(read)

    def set(self, key: str, value: Any) -> None:
        """Persists *value* under *key* as a JSON file (atomic write)."""

        def write() -> None:
            path = self.__path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".tmp.{os.getpid()}")
            with self.__lock:
                with open(tmp, "w") as fh:
                    json.dump(value, fh, default=str)
                    if self.__fsync:
                        fh.flush()
                        os.fsync(fh.fileno())
                os.replace(tmp, path)

        self.__circuit_call(write)

    def delete(self, key: str) -> bool:
        """Removes the file for *key*.  Returns ``True`` if it existed."""

        def delete() -> bool:
            path = self.__path(key)
            if not path.exists():
                return False
            with self.__lock:
                path.unlink(missing_ok=True)
            return True

        return self.__circuit_call(delete)

    def exists(self, key: str) -> bool:
        """Returns ``True`` if the file for *key* exists."""

        def exists() -> bool:
            return self.__path(key).exists()

        return self.__circuit_call(exists)

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        """Returns all keys, optionally filtered by a substring pattern.

        Args:
            pattern: Optional substring pattern to filter keys.
            limit: Max results (0 = unlimited).
            offset: Number of results to skip before returning.
        """

        def keys() -> list[str]:
            result: list[str] = []
            count: int = 0
            for path in self.__data_dir.rglob("*.json"):
                rel = str(path.relative_to(self.__data_dir))
                key = rel.replace(".json", "").replace("/", ":")
                if pattern is None or pattern.rstrip("*") in key:
                    if offset > 0 and count < offset:
                        count += 1
                        continue
                    result.append(key)
                    if limit > 0 and len(result) >= limit:
                        break
            return result

        return self.__circuit_call(keys)

    def __path(self, key: str) -> Path:
        safe = key.replace(":", "/")
        if ".." in safe or safe.startswith("/"):
            raise StoreError(f"invalid store key: {key}")
        full = (self.__data_dir / f"{safe}.json").resolve()
        data_dir = self.__data_dir.resolve()
        try:
            full.relative_to(data_dir)
        except ValueError as e:
            raise StoreError(f"key {key} resolves outside data directory") from e
        if full.is_symlink():
            resolved = full.resolve()
            try:
                resolved.relative_to(data_dir)
            except ValueError as e:
                raise StoreError(f"key {key} resolves to symlink outside data directory") from e
        return full


class PostgresStore(Store):
    """PostgreSQL-backed key-value store with connection pooling and circuit breaker.

    Uses ``psycopg2.pool.ThreadedConnectionPool`` for safe, bounded,
    connection-pooling across threads.  Connections are validated on
    checkout (``pool_pre_ping``) and recycled after 30 minutes.

    Requires the ``postgres`` extra (``psycopg2-binary``).
    """

    def __init__(
        self, dsn: str = "", table: str = "store", pool_size: int = 5, operation_timeout: float = 30.0
    ) -> None:
        self.__dsn: str = dsn
        import re as re_mod

        if not re_mod.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
            raise StoreError(f"invalid table name: {table!r}")
        self.__table: str = table
        self.__pool_size: int = pool_size
        self.__operation_timeout: float = operation_timeout
        self.__pool: Any = None
        self.__circuit: CircuitBreaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=15.0,
            name="postgres",
        )
        retryable: tuple[type[Exception], ...] = (
            ConnectionResetError,
            TimeoutError,
        )
        try:
            import psycopg2 as psycopg2_module

            retryable = (
                *retryable,
                psycopg2_module.OperationalError,
                psycopg2_module.InterfaceError,
            )
        except ImportError:
            pass
        self.__retry: RetryPolicy = RetryPolicy(
            max_retries=2,
            base_delay=0.05,
            retryable_exceptions=retryable,
        )
        self.__lock: threading.Lock = threading.Lock()
        self.__sql_get: str = self._build_sql("SELECT value FROM {} WHERE key = %s", table)
        self.__sql_set: str = self._build_sql(
            "INSERT INTO {} (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            table,
        )
        self.__sql_delete: str = self._build_sql("DELETE FROM {} WHERE key = %s RETURNING *", table)
        self.__sql_exists: str = self._build_sql("SELECT 1 FROM {} WHERE key = %s", table)
        self.__sql_keys_all: str = self._build_sql("SELECT key FROM {}", table)
        self.__sql_keys_pattern: str = self._build_sql("SELECT key FROM {} WHERE key LIKE %s", table)
        self.__timeout_sql: str = self._build_sql("SET statement_timeout = {}", str(int(operation_timeout * 1000)))

    def _get_pool(self) -> Any:
        if self.__pool is not None:
            return self.__pool
        try:
            from psycopg2 import pool as pgpool
        except ImportError:
            raise StoreError(
                "PostgresStore requires psycopg2-binary; install with: pip install underwrite[postgres]"
            ) from None
        with self.__lock:
            if self.__pool is not None:
                return self.__pool
            p = pgpool.ThreadedConnectionPool(
                minconn=max(1, self.__pool_size // 2),
                maxconn=self.__pool_size,
                dsn=self.__dsn,
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
            self.__pool = p
        return p

    @contextmanager
    def __connection(self) -> Generator[Connection, None, None]:
        pool = self._get_pool()
        conn = pool.getconn()
        close_conn = False
        try:
            conn.autocommit = True
            if self.__operation_timeout > 0:
                with conn.cursor() as cur:
                    cur.execute(self.__timeout_sql)
            yield conn
        except Exception:
            close_conn = True
            raise
        else:
            close_conn = False
        finally:
            try:
                if close_conn:
                    pool.putconn(conn, close=True)
                else:
                    pool.putconn(conn)
            except Exception:
                logger.warning("failed to return connection to pool", exc_info=True)

    def __execute(self, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]] | None:
        def run() -> Any:
            with self.__connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if cur.description:
                        return cur.fetchall()
                    return None

        return self.__circuit.call(lambda: self.__retry.execute(run))

    def get(self, key: str) -> Any | None:
        """Returns the value for *key*, or ``None``."""
        rows = self.__execute(self.__sql_get, (key,))
        if not rows:
            return None
        return json.loads(rows[0][0])

    def set(self, key: str, value: Any) -> None:
        """Persists *value* under *key* with an upsert."""
        self.__execute(
            self.__sql_set,
            (key, json.dumps(value)),
        )

    def delete(self, key: str) -> bool:
        """Removes *key*.  Returns ``True`` if it existed."""
        rows = self.__execute(self.__sql_delete, (key,))
        return rows is not None and len(rows) > 0

    def exists(self, key: str) -> bool:
        """Returns ``True`` if *key* is present."""
        rows = self.__execute(self.__sql_exists, (key,))
        return bool(rows)

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        """Returns all keys, optionally filtered by a LIKE pattern."""
        if pattern:
            like = f"%{pattern.rstrip('*')}%"
            sql: str = self.__sql_keys_pattern
            params: tuple[Any, ...] = (like,)
        else:
            sql = self.__sql_keys_all
            params = ()
        if limit > 0:
            sql += f" LIMIT {int(limit)}"
        if offset > 0:
            sql += f" OFFSET {int(offset)}"
        rows = self.__execute(sql, params)
        return [row[0] for row in (rows or [])]

    def health(self) -> dict[str, Any]:
        """Returns health status including circuit-breaker state."""
        try:
            self.__execute("SELECT 1")
            return {"ok": True, "circuit": self.__circuit.state.value}
        except Exception as e:
            logger.warning("PostgresStore health check failed: %s", e)
            return {"ok": False, "detail": "Postgres health check failed", "circuit": self.__circuit.state.value}

    @staticmethod
    def _build_sql(template: str, table: str) -> str:
        """Build a parameterised SQL statement from a template and a validated table name.

        Args:
            template: SQL template with ``{}`` placeholder for the table name.
            table: The validated table name (alphanumeric + underscore only).

        Returns:
            A safe parameterised SQL string.
        """
        return template.replace("{}", table)

    def migrate(self, plan: MigrationPlan) -> None:
        """Applies pending schema migrations to the Postgres store.

        Each migration runs inside a transaction so that partial failures
        roll back cleanly.  The version record is written in the same
        transaction as the schema changes.

        Args:
            plan: The migration plan to execute.

        Raises:
            MigrationError: If any migration fails.
        """
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS migrations ("
                    "version INTEGER PRIMARY KEY,"
                    "description TEXT NOT NULL,"
                    "applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ")"
                )
            conn.commit()

            with conn.cursor() as cur:
                cur.execute("SELECT version FROM migrations ORDER BY version")
                applied = {row[0] for row in cur.fetchall()}

            for migration in plan.pending(applied):
                try:
                    for stmt in migration.statements:
                        with conn.cursor() as cur:
                            cur.execute(stmt)
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO migrations (version, description) VALUES (%s, %s)",
                            (migration.version, migration.description),
                        )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    raise MigrationError(
                        f"migration v{migration.version} ({migration.description}) failed: {exc}"
                    ) from exc
        finally:
            conn.autocommit = True
            pool.putconn(conn)


class CQRSStore(Store):
    """CQRS wrapper — separates read and write stores.

    Writes go to the primary store, reads go to the read store.
    Useful when the read store is a replica or cache.
    """

    def __init__(self, write_store: Store, read_store: ReadStore) -> None:
        """Wraps a write store and a read store for CQRS separation.

        Args:
            write_store: Primary store for writes.
            read_store: Read-only store for queries.
        """
        self.__write: Store = write_store
        self.__read: ReadStore = read_store

    def get(self, key: str) -> Any | None:
        """Returns the value from the read store."""
        return self.__read.get(key)

    def set(self, key: str, value: Any) -> None:
        """Persists *value* to the write store and invalidates the read store."""
        self.__write.set(key, value)
        self.__read.delete(key)

    def delete(self, key: str) -> bool:
        """Removes *key* from the write store.  Returns ``True`` if it existed."""
        return self.__write.delete(key)

    def exists(self, key: str) -> bool:
        """Checks the read store for *key*."""
        return self.__read.exists(key)

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        """Returns keys from the read store, optionally filtered."""
        return self.__read.keys(pattern, limit=limit, offset=offset)

    def health(self) -> dict[str, Any]:
        """Returns health status for both read and write stores."""
        read_health = self.__read.health()
        try:
            write_health = self.__write.health()
        except Exception as exc:
            write_health = {"ok": False, "detail": str(exc)}
        combined_ok = read_health.get("ok", False) and write_health.get("ok", False)
        return {
            "ok": combined_ok,
            "read_store": read_health,
            "write_store": write_health,
        }

    def shutdown(self) -> None:
        """Shuts down both write and read stores."""
        self.__write.shutdown()
        self.__read.shutdown()

    def migrate(self, plan: MigrationPlan) -> None:
        """Applies migrations against the write store."""
        self.__write.migrate(plan)
