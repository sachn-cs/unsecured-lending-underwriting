# Database

underwrite persists all state through a single backend: SQLite
(``sqlite3`` from the Python standard library). The platform has no
PostgreSQL, no filesystem, no in-memory dict backend — there is one
store type with two path modes (``":memory:"`` for ephemeral,
file path for persistent). See `MIGRATIONS.md` for the schema and
`docs/CONFIGURATION.md` for the configuration surface.

> **Breaking change.** Earlier releases shipped with separate
> Memory, File and Postgres backends. Those have been removed in
> this revision. Existing Postgres data and on-disk JSON files
> are not migrated automatically — operators must extract data
> with their own tooling before upgrading, and start fresh on
> SQLite.

---

## Core Schema

### `store` Table

Created by migration v1. The primary key-value table used by all
nano services:

```sql
CREATE TABLE IF NOT EXISTS store (
    key   TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
```

| Column | Type | Notes |
|---|---|---|
| `key`   | `TEXT PK` | Namespaced key, e.g. `protocol:state`, `audit:ledger`, `saga:<uuid>` |
| `value` | `BLOB`    | JSON-serialised payload |

The migration runner keeps a companion `migrations` table that
records every version it has applied; pending versions are applied
on the next `Sqlite.migrate()` call inside a single `BEGIN IMMEDIATE`
transaction. Migrations are idempotent — re-running on a database
that already has all rows is a no-op.

---

## Connection Setup

`Sqlite` opens a `sqlite3.Connection` per operation (file-backed) or
keeps a single shared connection (`:memory:`) since SQLite gives each
private in-memory connection its own anonymous database. Every
connection is configured with:

| PRAGMA | Value | Reason |
|---|---|---|
| `journal_mode`   | `WAL`         | Readers do not block writers |
| `synchronous`    | `NORMAL`      | Durable enough for WAL |
| `foreign_keys`   | `ON`          | Enforce relational constraints |
| `busy_timeout`   | `30 s` (default) | Ride out transient locks |

`busy_timeout` is configurable through `Configuration.store.busy_timeout`
or `UNDERWRITE_STORE_BUSY_TIMEOUT`. The default is 30 s.

---

## Migration Tables

Created by the `Sqlite.migrate()` method in `store.py`:

### `migrations` Table

Tracks which schema versions have been applied:

```sql
CREATE TABLE IF NOT EXISTS migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

| Column | Notes |
|---|---|
| `version`     | Sequential integer, e.g. 1, 2, 3 |
| `description` | Human-readable, e.g. `"Event dead-letter queue"` |
| `applied_at`  | Set to `datetime('now')` when the migration runs |

### `dead_letters` Table

Created by migration v2. Captures failed events for replay:

```sql
CREATE TABLE IF NOT EXISTS dead_letters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     TEXT,
    error       TEXT NOT NULL,
    failed_at   TEXT NOT NULL DEFAULT (datetime('now')),
    replayed    INTEGER NOT NULL DEFAULT 0
);
```

### `metrics_snapshots` Table

Created by migration v3. Stores periodic metrics dumps:

```sql
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data        TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## Health Check

`Sqlite.health()` opens a connection and runs `SELECT 1`:

```json
{"ok": true, "path": "./store.db"}
```

If the path is corrupted or unreadable:

```json
{"ok": false, "path": "./store.db", "detail": "file is not a database"}
```

When SQLite reports a malformed-image error, `Sqlite` translates it
into a `StoreError` so the caller can treat the database as a hard
failure rather than a missing key. The translation also covers
SQLite's `database disk image is malformed` text.

---

## Concurrency

`Sqlite` is safe for multi-threaded use in a single process:

- A `threading.Lock` serialises writes and the in-memory DB connection.
- File-backed mode opens a fresh connection per operation and closes it
  in a `finally`, so the global interpreter lock plus `busy_timeout`
  cover cross-thread contention.
- `BEGIN IMMEDIATE` is used during migrations to acquire the write
  lock up front.

---

## Configuration Reference

```json
{
  "store": {
    "backend": "sqlite",
    "path": "./store.db",
    "busy_timeout": 30.0
  }
}
```

| Env Var | Config Key | Default |
|---|---|---|
| `UNDERWRITE_STORE_PATH`        | `store.path`        | `"./store.db"` |
| `UNDERWRITE_STORE_BUSY_TIMEOUT` | `store.busy_timeout` | `30.0`         |