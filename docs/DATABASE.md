# Database

underwrite uses a key-value abstraction (`Store`) with multiple backends.
`PostgresStore` is the production-grade backend; `MemoryStore` and
`FileStore` are for development and testing.

---

## Core Schema

### `store` Table

Created by migration v1.  The primary key-value table used by all
nano services:

```sql
CREATE TABLE IF NOT EXISTS store (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

| Column | Type | Notes |
|---|---|---|
| `key` | `TEXT PK` | Namespaced key, e.g. `protocol:state`, `audit:ledger`, `saga:<uuid>` |
| `value` | `TEXT` | JSON-serialised payload |
| `updated_at` | `TIMESTAMPTZ` | Set to `NOW()` on every UPSERT |

### Access Pattern

`PostgresStore` uses parameterized UPSERT for writes:

```sql
INSERT INTO store (key, value, updated_at)
VALUES (%s, %s, NOW())
ON CONFLICT (key) DO UPDATE
  SET value = EXCLUDED.value, updated_at = NOW();
```

Table name is regex-validated (`^[a-zA-Z_][a-zA-Z0-9_]*$`) to prevent
SQL injection.

---

## Connection Pool

`PostgresStore` uses `psycopg2.pool.ThreadedConnectionPool`:

| Config | Default | Description |
|---|---|---|
| `pool_size` | 5 | `maxconn = pool_size`, `minconn = pool_size // 2` |
| `dsn` | `""` | Postgres connection string (e.g. `postgresql://user:pass@host:5432/db`) |
| `operation_timeout` | `30.0` | Seconds, converted to `statement_timeout` ms |

### Connection Configuration

```python
pgpool.ThreadedConnectionPool(
    minconn=max(1, pool_size // 2),
    maxconn=pool_size,
    dsn=dsn,
    connect_timeout=10,
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5,
)
```

### Per-Connection Settings

```sql
SET statement_timeout = <operation_timeout_ms>;
```

Connections are returned to the pool with `pool.putconn()`.  Faulty
connections are closed (`putconn(conn, close=True)`) on exception.

---

## Migration Tables

Created by the `Store.migrate()` method in `store.py`:

### `migrations` Table

Tracks which schema versions have been applied:

```sql
CREATE TABLE IF NOT EXISTS migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

| Column | Notes |
|---|---|
| `version` | Sequential integer, e.g. 1, 2, 3 |
| `description` | Human-readable, e.g. `"Event dead-letter queue"` |
| `applied_at` | Set to `NOW()` when the migration runs |

### `dead_letters` Table

Created by migration v2.  Captures failed events for replay:

```sql
CREATE TABLE IF NOT EXISTS dead_letters (
    id          SERIAL PRIMARY KEY,
    event_id    TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     TEXT,
    error       TEXT NOT NULL,
    failed_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    replayed    BOOLEAN NOT NULL DEFAULT FALSE
);
```

### `metrics_snapshots` Table

Created by migration v3.  Stores periodic metrics dumps:

```sql
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id           SERIAL PRIMARY KEY,
    data         JSONB NOT NULL,
    captured_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

---

## Circuit Breaker & Retry

`PostgresStore` wraps all queries in a two-layer resilience pattern:

### Circuit Breaker

- **Threshold:** 3 consecutive failures
- **Recovery:** 15 seconds (half-open → closed on success)
- **State:** exposed in `health()` as `"circuit": "closed"|"open"|"half_open"`

### Retry Policy

- **Max retries:** 2 (3 total attempts including initial)
- **Base delay:** 50ms
- **Backoff:** Exponential with jitter:
  `delay = min(0.05 * 2^attempt + random(0, 0.01), max_delay)`

```python
self.__retry = RetryPolicy(max_retries=2, base_delay=0.05)
```

---

## CQRS

`CQRSStore` (`underwrite/store.py:566-629`) separates read and write
stores:

- **Writes** go to the primary (`write_store`).
- **Reads** go to the read replica (`read_store`).
- On write, the read store key is **invalidated** (deleted) to prevent
  stale reads.

Configured in Runtime via `store.read_backend` and `store.read_dsn`.

Example: write to Postgres, read from MemoryStore:

```python
CQRSStore(write_store=PostgresStore(dsn=...), read_store=MemoryStore())
```

---

## Dead-Letter Queue Persistence

The in-memory `DeadLetterQueue` optionally persists to a `Store`:

- Store key: `bus:dlq`
- Format: `list[dict]` — each entry is a serialised `DeadLetterRecord`
- Sync interval: configurable (default every 10 `put()` calls)
- On startup, persisted records are loaded back into memory

---

## Health Check

`PostgresStore.health()` executes `SELECT 1` against the pool and
returns circuit-breaker state:

```json
{"ok": true, "circuit": "closed"}
```

On failure:

```json
{"ok": false, "detail": "Postgres health check failed", "circuit": "open"}
```

---

## Configuration Reference

```json
{
  "store": {
    "backend": "postgres",
    "dsn": "postgresql://user:pass@localhost:5432/underwrite",
    "pool_size": 5,
    "read_backend": "memory",
    "read_dsn": ""
  }
}
```

| Env Var | Config Key | Default |
|---|---|---|
| `UNDERWRITE_STORE_DSN` | `store.dsn` | `""` |
| `UNDERWRITE_STORE_POOL_SIZE` | `store.pool_size` | `5` |
| `UNDERWRITE_STORE_READ_DSN` | `store.read_dsn` | `""` |
