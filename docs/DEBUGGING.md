# Debugging Guide

## Logging

Configure logging via environment variables or `underwrite.json`:

```bash
export UNDERWRITE_LOG_LEVEL=DEBUG
export UNDERWRITE_LOG_FORMAT=json      # structured JSON (default: text)
export UNDERWRITE_LOG_OUTPUT=stdout    # or stderr
```

When `log_format` is `"json"`, each log line is a JSON object with `timestamp`, `level`, `logger`, `message`, `module`, `line`, and optional `correlation_id`, `trace_id`, and `exception` fields. Sensitive fields (`password`, `secret`, `token`, `ssn`, `pan`, etc.) are automatically redacted to `***REDACTED***`.

Logging runs through loguru; all code imports `logger` from `underwrite.logger`, and the formatters read the current thread's correlation ID from the shared context in `underwrite/correlation.py`. Set log level to `DEBUG` for detailed event dispatch tracing.

---

## Checking the Dead Letter Queue

Events that fail processing are captured in the DLQ with the subscriber ID, error message, and timestamp.

```bash
# Show DLQ contents
underwrite dlq

# Replay all dead-letter events
underwrite dlq --replay

# Replay at most 10 events
underwrite dlq --replay --max 10
```

The DLQ records are stored in `data/bus/dlq.json` when using `underwrite.store.Sqlite`, or in the `dead_letters` table when using `underwrite.store.Sqlite`. To inspect directly:

```bash
# underwrite.store.Sqlite:
cat data/bus/dlq.json | python -m json.tool

# underwrite.store.Sqlite:
psql $DATABASE_URL -c "SELECT * FROM dead_letters WHERE replayed=false ORDER BY failed_at DESC LIMIT 10;"
```

To clear the DLQ programmatically:

```python
from underwrite.bus import DeadLetterQueue

dlq = DeadLetterQueue()
dlq.clear()
```

---

## Health Checks

### CLI

```bash
underwrite health
```

Output:

```
Status: healthy
OK: True
Checks:
  [OK] bus — subscribers=4 dlq_count=0
  [OK] store — circuit=closed
  [OK] services — running=['mechanism', 'audit']
  [OK] saga
  [OK] dlq — dead_letter_count=0
```

### HTTP Endpoints (when running `underwrite serve`)

| Endpoint | Purpose | Status Code |
|----------|---------|-------------|
| `GET /healthz` | Kubernetes liveness probe | 200 if healthy, 503 if degraded |
| `GET /readyz` | Kubernetes readiness probe | 200 if healthy, 503 if degraded |
| `GET /v1/health` | Full health report | 200 with JSON body |
| `GET /health` | Legacy unversioned health | 200 with JSON body |

### Health Check Subsystems

The Runtime registers health checks for:
- **bus** — subscriber count, DLQ count, running state
- **store** — backend connectivity and circuit breaker state
- **read_store** — if CQRS read store is configured
- **services** — list of running services
- **metrics** — collector availability
- **tracer** — span count
- **saga** — orchestrator availability
- **dlq** — dead-letter queue count
- **supervisor** — service restart status and failure counts
- **service:<name>** — per-service health (running state, events handled/failed)

---

## Metrics Snapshot

```bash
underwrite metrics
```

Output:

```
Counters:
  events.emitted:service=mechanism:event_type=seed.added: 12
  events.handled:service=audit:event_type=seed.added: 12
Timers:
  handle.duration:service=audit:event_type=seed.added: count=12 avg=1.2ms min=0.3ms max=3.1ms
```

HTTP endpoint: `GET /v1/metrics` (Prometheus text format, requires `underwrite[serve]` extra).

---

## Testing a Single Service

Create a minimal test script that instantiates a `Runtime` with one service:

```python
from underwrite.config import Configuration
from underwrite.message import Event
from underwrite.runtime import Runtime

cfg = Configuration.default()
cfg.store.backend = "memory"
cfg.authz.enabled = False
cfg.metrics.export_interval = 0

rt = Runtime(config=cfg)
rt.register("fee")
rt.wire("fee")
rt.bus.start()
rt.start(["fee"])

svc = rt.get("fee")
svc.handle(Event(event_type="fee.assess", source="debug", payload={"loan_id": "DBG1", "fee_type": "late_payment"}))
print("Keys:", svc.store.keys("fee:"))
rt.stop()
```

Run with: `python debug_fee.py` or set `UNDERWRITE_LOG_LEVEL=DEBUG python debug_fee.py`.

---

## Common Failures

### Store Not Configured

The default store backend is `"filesystem"` (data in `./data/`). If the directory is not writable:

```
RuntimeError: [Errno 13] Permission denied: './data/protocol:state.json'
```

Set `UNDERWRITE_STORE_BACKEND=memory` for ephemeral use or ensure `data/` exists and is writable.

### Missing Environment Variables

| Variable | Required For |
|----------|-------------|
| `UNDERWRITE_API_TOKEN` | `underwrite serve --require-auth` |
| `VAULT_TOKEN` | Secrets backend `vault` |
| `UNDERWRITE_STORE_PATH` | Sqlite database path (default `./store.db`) |

### Signature Mismatch

Event signatures are verified with Ed25519. If a subscriber rejects an event, check:

```python
# In logs:
WARNING  signature verification failed for <event_id> from <source>
```

The emitter's public key must be trusted by the subscriber's `AccessControl`. Check authz policies in `underwrite.json`:

```json
{ "allow": [{ "subject": "audit", "resource": "*" }] }
```

### Rate Limiting

The bus rate-limits per subscriber. If events go to DLQ with `"rate_limited"`:

```
UNDERWRITE_BUS_RATE_LIMIT=500    # increase
```

Or disable rate limiting: `rate_limit: 0` in config.

---

## Checking Event Flow

Subscribe a wildcard handler to capture all events:

```python
from underwrite.bus import LocalBus

bus = LocalBus()
all_events: list = []
bus.subscribe("*", lambda e: all_events.append(e))
bus.start()
# ... emit events ...
for e in all_events:
    print(f"{e.event_type} from {e.source}")
```

For HTTP debugging, publish test events:

```bash
curl -X POST http://localhost:8080/v1/publish \
  -H "Content-Type: application/json" \
  -d '{"event_type": "loan.originated", "payload": {"borrower": "test", "principal": 10000}}'
```

Every response includes an `X-Request-ID` header for correlation.

---

## Migration Debugging

```bash
# Check applied migrations (underwrite.store.Sqlite)
psql $DATABASE_URL -c "SELECT * FROM migrations ORDER BY version;"

# Manual rollback
psql $DATABASE_URL -c "DELETE FROM migrations WHERE version=3;"

# Re-run migrations
underwrite migrate
```

The `migrations` table is created automatically. If auto-migrate is disabled in config (`migration.auto_migrate: false`), run `underwrite migrate` manually.

Migration versions are defined in `underwrite/migrate.py` (`default_plan()`). Current versions:

| Version | Description |
|---------|-------------|
| 1 | Initial store schema (key-value table + migrations table) |
| 2 | Event dead-letter queue table |
| 3 | Metrics snapshot table |

---

## Circuit Breaker

Circuit breakers protect the store and the bus. When tripped, the log shows:

```
WARNING  circuit store failure 3/3
WARNING  circuit store tripped open (3 failures)
```

When a circuit opens, operations fail with `CircuitBreakerOpenError`. Recovery is automatic after the cooldown period:

| Component | Failure Threshold | Recovery Timeout |
|-----------|-------------------|------------------|
| underwrite.store.Sqlite circuit | 3 failures | 15 seconds |
| underwrite.store.Sqlite circuit | 3 failures | 30 seconds |
| Bus per-subscriber circuit | 5 failures | 60 seconds |

Check circuit state:

```python
from underwrite.circuit import CircuitBreaker

cb = CircuitBreaker()
print(cb.state)  # CircuitState.CLOSED / OPEN / HALF_OPEN
```

Or via health: `underwrite health` shows `circuit=closed` in store checks.

---

## Saga Failures

Sagas coordinate multi-step distributed transactions. Inspect saga state:

```python
orchestrator = rt.saga
saga = orchestrator.get_saga("saga-id-here")
print(f"Status: {saga.status}")  # started / completed / compensating / rolled_back
print(f"Steps: {len(saga.steps)}")
print(f"Completed: {saga.completed_steps}")
print(f"Error: {saga.error}")
```

Replay an incomplete saga (e.g., after a crash):

```python
success = orchestrator.replay_saga("saga-id-here")
```

From CLI, use `Runtime.replay_saga()`:

```python
rt = Runtime()
rt.replay_saga("saga-id-here")
```

Saga state is persisted to the store under keys `saga:<saga_id>`. An idempotency key `saga_step:<saga_id>:<step_index>` ensures safe replay after crash recovery.

---

## Supervisor and Auto-Restart

The supervisor tracks service failures and auto-restarts crashed services:

```python
# Check supervisor health
print(rt.supervisor.health())
# {'ok': True, 'total_failures': 1, 'restarting': ['fee']}
```

Exponential backoff: 1s → 2s → 4s → ... capped at 60s. After `max_restarts` (default 3) consecutive failures, the service is permanently marked unhealthy.

To disable auto-restart: `UNDERWRITE_RECOVERY_AUTO_RESTART=false` or `recovery.auto_restart: false` in config.

---

## Quick Reference

| Symptom | Check |
|---------|-------|
| Service not receiving events | `underwrite health` → subscriptions count, running services |
| Events going to DLQ | `underwrite dlq` for error messages |
| Slow handlers | `underwrite metrics` for `handle.duration` timers |
| Circuit breaker tripped | Log: `circuit open`, `underwrite health` → store circuit state |
| Saga stuck | `orchestrator.get_saga(id)` → inspect status and error |
| Signature mismatch | Log: `signature verification failed`, check authz policies |
| Config not loading | Check `underwrite.json` exists, no unknown keys |
| Migration failure | `psql` → `SELECT * FROM migrations`, check error in logs |
