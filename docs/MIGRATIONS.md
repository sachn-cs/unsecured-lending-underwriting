# Migrations

underwrite has a lightweight SQLite-native migration engine for schema
changes. Migrations are versioned, ordered, and applied in single
transactions. Idempotency is enforced through a `migrations` table
that records every version the runner has applied.

---

## Architecture

**Module:** `underwrite/migrate.py`

### Migration

A single schema migration:

```python
@dataclass
class Migration:
    version: int
    description: str
    statements: tuple[str, ...]  # SQLite SQL statements
```

### MigrationPlan

An ordered collection of `Migration` objects:

- `add(migration)` — registers a migration (duplicate version raises
  `MigrationError`).
- `pending(applied)` — returns un-applied migrations sorted by version.
- `latest_version` — highest registered version number.

---

## Default Plan

`default_plan()` in `migrate.py:84` defines three migrations:

### v1 — Initial Schema

```sql
CREATE TABLE IF NOT EXISTS store (
    key   TEXT PRIMARY KEY,
    value BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### v2 — Dead-Letter Queue

```sql
CREATE TABLE IF NOT EXISTS dead_letters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source     TEXT NOT NULL,
    payload    TEXT,
    error      TEXT NOT NULL,
    failed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    replayed   INTEGER NOT NULL DEFAULT 0
);
```

### v3 — Metrics Snapshots

```sql
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data        TEXT NOT NULL,
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## Migration Execution

### Trigger

Migrations run automatically when `Runtime.start()` is called and
`config.migration.auto_migrate` is `true` (default).

The `underwrite migrate` CLI command also runs pending migrations:

```
underwrite migrate
```

### `Sqlite.migrate()`

`Sqlite.migrate(plan)` (`store.py`):

1. Creates the `migrations` tracking table if it doesn't exist.
2. Reads the set of already-applied migration versions.
3. For each pending migration:
   - Begins an immediate write transaction (`BEGIN IMMEDIATE`).
   - Executes each SQL statement.
   - Inserts a row into `migrations`.
   - Commits. On failure: rolls back and raises `MigrationError`.
4. The whole plan runs serially — a single failed migration aborts
   the rest. Re-running `migrate()` after a fix only applies the
   versions that were not previously recorded.

```python
for migration in plan.pending(applied):
    conn.execute("BEGIN IMMEDIATE")
    for stmt in migration.statements:
        conn.execute(stmt)
    conn.execute(
        "INSERT OR IGNORE INTO migrations (version, description) VALUES (?, ?)",
        (migration.version, migration.description),
    )
    conn.commit()
```

### Idempotency

The runner reads existing versions from `migrations` before applying
anything. A version that is already present is skipped. The
`INSERT OR IGNORE` on the bookkeeping row means that even a manually
inserted migration row does not cause a duplicate-key error.

---

## Adding a Migration

To add a new migration, extend `default_plan()` or create your own plan:

```python
from underwrite.migrate import Migration, MigrationPlan, default_plan

plan = default_plan()

plan.add(
    Migration(
        version=4,
        description="Interest rate cache",
        statements=(
            "CREATE TABLE IF NOT EXISTS rate_cache ("
            "  borrower TEXT PRIMARY KEY,"
            "  rate REAL NOT NULL,"
            "  computed_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")",
        ),
    )
)
```

Then apply it:

```python
store.migrate(plan)
```

**Constraints:**
- Versions must be unique (duplicate raises `MigrationError`).
- Versions must be strictly increasing integers (1, 2, 3, ...).
- Statements are executed in order inside a single transaction per
  migration version.

---

## Rollback

There is no automated rollback. To revert a migration:

1. Manually undo the schema changes with `DROP TABLE` / `ALTER TABLE`.
2. Delete the version record:

```sql
DELETE FROM migrations WHERE version = N;
```

3. The migration will be re-applied on the next `migrate()` call.

---

## CLI Commands

```
underwrite migrate          # Run pending migrations
```

The `migrate` command creates a `Runtime` (which triggers auto-migrate
on construction if `auto_migrate` is true) and exits.

---

## Configuration

```json
{
  "migration": {
    "auto_migrate": true
  }
}
```

| Env Var | Config Key | Default | Description |
|---|---|---|---|
| `UNDERWRITE_AUTO_MIGRATE` | `migration.auto_migrate` | `true` | Run migrations on `Runtime.start()` |

---

## SQLite-Only

| Store | `migrate()` | Behaviour |
|---|---|---|
| `Sqlite` | SQL | Executes `statements` in `BEGIN IMMEDIATE` transactions, idempotent via `migrations` table |