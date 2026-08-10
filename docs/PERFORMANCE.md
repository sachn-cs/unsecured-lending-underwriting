# Performance

This document covers the performance characteristics,  known bottlenecks,
and scaling considerations of the underwrite nano-service platform.

---

## Event Bus

### LocalBus (`underwrite/bus.py`)

The in-process event bus has **zero serialisation overhead** — events are
passed as Python objects via direct function calls, not serialised.
Dispatch flow:

1. `LocalBus.publish()` appends to an in-memory buffer.
2. On `start()` or flush, matching subscribers are called synchronously
   or via `ThreadPoolExecutor` (configurable `max_workers`).
3. Each subscriber goes through circuit-breaker check → rate-limit check →
   dispatch.

**Defaults:**

| Parameter | Default | Description |
|---|---|---|
| `max_workers` | `0` | 0 = synchronous dispatch in publisher's thread |
| `max_futures` | `10000` | Max pending futures before backpressure cleanup |
| `max_buffer_size` | `0` | 0 = unlimited buffer |

**Backpressure:** When `max_buffer_size > 0`, the oldest buffered event is
dropped if the buffer is full.  Completed futures are trimmed from the
pending list every time a new future is added.

**Implication:** There is **no distributed bus** yet.  `backend` in config
accepts `local`, `sqs`, `modal` but only `local` is implemented.  Scaling
beyond a single process requires implementing an `EventBus` subclass.

---

## Store Performance

### MemoryStore (`underwrite/store.py`)

`MemoryStore` is backed by a `dict`.  All operations are **O(1)**:

| Operation | Complexity |
|---|---|
| `get` | O(1) — dict lookup |
| `set` | O(1) — dict insert; O(n) eviction when at capacity, amortised O(1) |
| `delete` | O(1) — dict pop |
| `exists` | O(1) — key in dict |
| `keys` | O(n) — full scan with optional substring filter |

Bounded by `max_entries` (default 0 = unlimited).  When the limit is
reached, the oldest key (by insertion order) is evicted.

### FileStore (`underwrite/store.py`)

Each key maps to a `.json` file on disk.  Writes are atomic (`write` →
`os.replace`):

| Operation | Complexity |
|---|---|
| `get` | O(1) — file read + `json.load` |
| `set` | O(1) — atomic write with fsync |
| `delete` | O(1) — file unlink |
| `exists` | O(1) — `Path.exists()` |
| `keys` | **O(n)** — `Path.rglob("*.json")` scans entire directory tree (no pagination) |

Configurable `operation_timeout` wraps I/O in a single-thread executor.
Optional `CircuitBreaker` (3 failures, 30s recovery) guards against
stuck filesystems.

**Path traversal protection:** `__path()` validates the resolved path is
inside `data_dir` and that symlinks do not escape.

### PostgresStore (`underwrite/store.py`)

Connection pool via `psycopg2.pool.ThreadedConnectionPool`:

| Parameter | Default | Description |
|---|---|---|
| `pool_size` | `5` | `maxconn = pool_size`, `minconn = pool_size // 2` |
| `operation_timeout` | `30.0` | `statement_timeout` set per connection (ms) |
| `dsn` | `""` | Postgres connection string |

TCP keepalives: `keepalives=1, keepalives_idle=30, keepalives_interval=10,
keepalives_count=5`.

| Operation | Complexity |
|---|---|
| `get` | O(log n) — B-tree index on `key` |
| `set` | O(log n) — UPSERT |
| `delete` | O(log n) |
| `exists` | O(log n) |
| `keys` | O(log n + m) — indexed scan with `LIKE` filter |

Circuit breaker: 3 failures → open, 15s recovery.  Retry policy: 2
retries, 50ms base delay with jitter (exponential backoff).

---

## Known Bottlenecks

### 1. AuditService — Export builds full ledger string in memory

**File:** `underwrite/services/audit.py:104-107`

```python
lines: list[str] = [json.dumps(r) for r in self.__ledger]
body: str = "\n".join(lines) + "\n"
```

The entire ledger is serialised into memory as a single string before
being uploaded to S3/GCS.  For a ledger of 100k+ records this can
consume 100s of MB and cause OOM.  The `save_jsonl()` method streams
in chunks as a workaround.

### 2. DelegationGraph — Recursive chain traversal

**File:** `underwrite/services/mechanism/graph.py:55-67`

`required_delegation()` walks the delegation tree recursively with a
maximum depth of 50.  Each call traverses the full sub-tree, making it
**O(depth × branching factor)**.  `credit_limit()` is O(1) — it only
reads the direct sponsor's delegation edge.

### 3. Saga Persistence — 7+ store writes per event

**File:** `underwrite/saga.py`

Each `execute_step` call writes:
- 1 idempotency key (`saga_step:{saga_id}:{step_index}`)
- 1 full saga state update (`saga:{saga_id}`)

For an N-step saga, this is 2N store sets + the initial `start_saga`
write and the final completion write.

### 4. FileStore.keys() — Unbounded rglob scan

`keys()` calls `Path.rglob("*.json")` which scans every file in the
data directory tree.  There is **no server-side pagination** and no
index.  For data directories with 100k+ files this becomes a
multi-second operation.

---

## Resilience Patterns

### Circuit Breaker

Two circuit breaker implementations:

| Location | Threshold | Recovery | Use |
|---|---|---|---|
| `circuit.py` (store-level) | 5 failures | 30s | Guards store I/O |
| `bus.py` (subscriber-level) | 5 failures | 60s | Per-subscriber dispatch gating |

When a circuit is open, the subscriber is skipped and events go to the
DLQ instead of blocking the publisher.

### Retry Policy

`RetryPolicy` in `circuit.py` implements exponential backoff with
jitter:

```
delay = min(base_delay * 2^attempt + random(0, 0.1), max_delay)
```

Defaults: `max_retries=3, base_delay=0.1s, max_delay=5.0s`.  Used by
`PostgresStore.__execute()` (2 retries, 50ms base delay).

### Dead-Letter Queue

`DeadLetterQueue` captures events that fail processing.  Bounded by
`max_records=10000` (oldest evicted).  Optionally persisted to a `Store`
with batched sync (every N puts, default interval 10).

### Supervisor

`ServiceSupervisor` tracks consecutive handler failures per service.
After `max_restarts=3` failures, the service is permanently marked
unhealthy.  `Runtime.restart_failing_services()` re-registers and
re-starts failed services with exponential backoff.

---

## Scaling Considerations

| Concern | Current State | Path Forward |
|---|---|---|
| **Inter-service communication** | Single-process `LocalBus` | Implement `SQSBackend` or `ModalBackend` |
| **State storage** | MemoryStore, FileStore, PostgresStore | Shard by key prefix or use distributed KV |
| **Concurrent dispatch** | `ThreadPoolExecutor` per service (optional) | Increase `max_workers` for I/O-bound handlers |
| **Audit ledger size** | Bounded in-memory deque + batched persist | Offload to append-only log (Kafka, PGD) |
| **Metrics collection** | Single `MetricsCollector` instance | Push to Prometheus Pushgateway for multi-process |
| **Migrations** | Synchronous, single-connection | Parallel migration runners for zero-downtime deploys |

---

## Profiling Tips

- Set `UNDERWRITE_LOG_LEVEL=DEBUG` to see event dispatch timing in logs.
- Enable tracing with `tracing.exporter=console` to see per-handler
  duration at `INFO` level.
- The `underwrite metrics` CLI command dumps current counters and timers.
- `FileStore` and `PostgresStore` expose `circuit` state in health checks.
