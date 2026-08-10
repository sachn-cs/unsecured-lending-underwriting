# Migrations

underwrite has a lightweight, store-agnostic migration engine for schema
changes.  Migrations are versioned, ordered, and applied in transactions.

---

## Architecture

**Module:** `underwrite/__migrate__.py`

### Migration

A single schema migration:

```python
@dataclass
class Migration:
    version: int
    description: str
    statements: list[str]  # SQL statements (for SQL stores)
    fn: Callable[[Any], None] | None  # callable (for any store)
```

### MigrationPlan

An ordered collection of `Migration` objects:

- `add(migration)` — registers a migration (duplicate version raises
  `MigrationError`).
- `pending(applied)` — returns un-applied migrations sorted by version.
- `latest_version` — highest registered version number.

---

## Default Plan

`default_plan()` in `__migrate__.py:74` defines three migrations:

### v1 — Initial Schema

```sql
CREATE TABLE IF NOT EXISTS store (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

### v2 — Dead-Letter Queue

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

### v3 — Metrics Snapshots

```sql
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id           SERIAL PRIMARY KEY,
    data         JSONB NOT NULL,
    captured_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
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

### PostgresStore

`PostgresStore.migrate()` (`__store__.py:515-563`):

1. Creates the `migrations` tracking table if it doesn't exist.
2. Reads the set of already-applied migration versions.
3. For each pending migration:
   - Executes each SQL statement.
   - Inserts a row into `migrations`.
   - Entire migration runs in a **single transaction**.
   - On failure: **transaction rolled back**, `MigrationError` raised.
4. Connection is returned to the pool in the `finally` block.

```python
# Pseudocode
conn.autocommit = False
for migration in plan.pending(applied):
    try:
        for stmt in migration.statements:
            cur.execute(stmt)
        cur.execute("INSERT INTO migrations ...", (version, description))
        conn.commit()
    except Exception:
        conn.rollback()
        raise MigrationError(...)
```

### MemoryStore / FileStore

`Store.migrate()` is a **no-op** by default.  These stores have no schema
to migrate.

### CQRSStore

`CQRSStore.migrate()` delegates to the **write store** (`__store__.py:627`):

```python
def migrate(self, plan):
    self.__write.migrate(plan)
```

---

## Adding a Migration

To add a new migration, extend `default_plan()` or create your own plan:

```python
from underwrite.__migrate__ import Migration, MigrationPlan, default_plan

plan = default_plan()

plan.add(
    Migration(
        version=4,
        description="Interest rate cache",
        statements=[
            "CREATE TABLE IF NOT EXISTS rate_cache ("
            "  borrower TEXT PRIMARY KEY,"
            "  rate FLOAT NOT NULL,"
            "  computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
            ")",
        ],
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

There is no automated rollback.  To revert a migration:

1. Manually undo the schema changes with `ALTER TABLE` / `DROP TABLE`.
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

## Store-Agnostic Design

| Store | `migrate()` | Behaviour |
|---|---|---|
| `MemoryStore` | No-op | No schema to manage |
| `FileStore` | No-op | No schema to manage |
| `PostgresStore` | SQL | Executes `statements` in transactions |
| `CQRSStore` | Delegates | Forwards to write `Store.migrate()` |
