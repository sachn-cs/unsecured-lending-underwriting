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

### Sqlite (`underwrite/store.py`)

`Sqlite` is backed by the standard library `sqlite3` module. All
operations run inside a `threading.Lock`; file-backed mode opens a
fresh `sqlite3.Connection` per call (the connection is closed in a
`finally`), while `:memory:` mode reuses a single shared connection
because SQLite gives each private in-memory connection its own
anonymous database.

| Parameter | Default | Description |
|---|---|---|
| `path` | `":memory:"` | SQLite path. `":memory:"` is ephemeral. |
| `busy_timeout` | `30.0` | Seconds the driver waits on a busy lock. |

| Operation | Complexity |
|---|---|
| `get` | O(log n) — B-tree index on `key` |
| `set` | O(log n) — UPSERT |
| `delete` | O(log n) |
| `exists` | O(log n) |
| `keys` | O(log n + m) — indexed scan with substring filter |

PRAGMAs: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`.
The migration runner uses `BEGIN IMMEDIATE` for transactional
schema updates.

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

### 4. Sqlite.keys() — Unbounded table scan

`keys()` returns every row from the `store` table sorted by `key`
and then applies the optional substring filter in Python. For
tables with 100k+ rows the scan is single-digit milliseconds but
loads everything into memory; use `limit`/`offset` for pagination
when callers need bounded slices.

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
Callers that want retry semantics around the store can wrap calls
in their own `RetryPolicy` (`underwrite.circuit`).

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
| **State storage** | Sqlite (file or `:memory:`) | Shard by key prefix or replace with a distributed KV for multi-node |
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
- `Sqlite` reports `path` and `ok` in `health()` and surfaces a
  `StoreError` on corruption.
