# Operations Guide

## Startup

### CLI

```bash
# Start one or more services interactively
underwrite run mechanism audit risk

# Start as HTTP daemon (default: mechanism,audit)
underwrite serve
underwrite serve --host 0.0.0.0 --port 8080
underwrite serve --services "mechanism,audit,fraud" --rate-limit 200

# With auth
UNDERWRITE_API_TOKEN=prod-token underwrite serve --require-auth

# Init default config
underwrite init
underwrite init config.production.json
```

The `run` command starts services in the foreground with a synchronous event loop. The `serve` command wraps them in a FastAPI/uvicorn HTTP server.

### Configuration Loading

On startup, the Runtime loads configuration in this order:

1. `underwrite.json` in working directory (if it exists)
2. `config.<UNDERWRITE_ENV>.json` (if `UNDERWRITE_ENV` is set)
3. Environment variable overrides (`UNDERWRITE_*`)

Create a default config with `underwrite init` — it enables `mechanism` and `audit` by default.

---

## Shutdown

### Graceful Shutdown

Send `SIGTERM` or `SIGINT` (Ctrl+C):

```bash
kill <pid>
docker stop underwrite
```

The Runtime performs an orderly shutdown:

1. Stops the metrics export loop
2. Stops all registered services (unsubscribes from bus)
3. Stops the event bus (flushes remaining events, waits for pending futures up to 5s)
4. Shuts down store backends (closes connection pools, shuts down thread pools)

The `serve` command supports `--shutdown-timeout 30` (default 30s) for the HTTP server's graceful drain period.

### Forcing Shutdown

`SIGKILL` (kill -9) is safe—saga idempotency keys in the store prevent duplicate event processing on restart.

---

## Supervisor Auto-Restart

The `ServiceSupervisor` monitors service handler failures and auto-restarts crashed services.

Enable/disable with:

```bash
UNDERWRITE_RECOVERY_AUTO_RESTART=true    # enable (default)
UNDERWRITE_RECOVERY_AUTO_RESTART=false   # disable
```

Configured via:

```json
{
  "recovery": {
    "auto_restart": true,
    "max_restarts": 5,
    "backoff_seconds": 2.0
  }
}
```

### Behaviour

- After a handler exception, the supervisor records a failure
- Exponential backoff before restart: `backoff_seconds * 2^(failure-1)`, capped at 60s
- After `max_restarts` consecutive failures, the service is marked permanently unhealthy
- On successful handler execution, the failure count resets
- The supervisor health check reports restarting services and total failures

### Runtime Restart

The Runtime's `restart_failing_services()` method re-registers, re-wires, and re-starts failing services:

```python
restarted = rt.restart_failing_services()
print(f"Restarted: {restarted}")  # ['fee', 'risk']
```

---

## Circuit Breaker

The platform uses two layers of circuit breakers:

### Bus Circuit Breaker (per-subscriber)

Tracks failures per subscriber ID (not per service). After 5 consecutive failures, the circuit opens for 60 seconds. While open, events are sent directly to the DLQ without invoking the handler. A successful request on the half-open state resets the circuit.

### Store Circuit Breaker

| Store | Failure Threshold | Recovery Timeout |
|-------|-------------------|------------------|
| PostgresStore | 3 | 15 seconds |
| FileStore | 3 | 30 seconds |

When tripped, all store operations raise `CircuitBreakerOpenError`. Check state via health:

```bash
underwrite health
# [OK] store — circuit=closed
```

Or programmatically:

```python
from underwrite.__circuit__ import CircuitBreaker, CircuitState
cb = CircuitBreaker(failure_threshold=3, recovery_timeout=15.0)
# cb.state → CircuitState.CLOSED / OPEN / HALF_OPEN
```

Recovery is automatic after the cooldown period. No manual reset required.

---

## Dead Letter Queue

The DLQ captures events that failed processing (handler exceptions, rate limiting, open circuits).

### Inspect

```bash
underwrite dlq
```

Output:

```
Dead-letter queue: 3 entries
  [1717785600.0] subscriber-id: fee.assess — ProtocolError: must be finite
  [1717785601.5] subscriber-id: risk.scored — RateLimitError: rate limit exceeded
  [1717785602.0] subscriber-id: fraud.alert — CircuitBreakerOpenError: circuit is open
```

### Replay

```bash
underwrite dlq --replay            # replay all
underwrite dlq --replay --max 10   # replay at most 10
```

Replayed events are re-published to the bus. Services with idempotency guards skip duplicate events. The DLQ is bounded at 10,000 records (oldest evicted first).

### Persistence

When `FileStore` or `PostgresStore` is used, the DLQ persists across restarts:

- **FileStore**: `data/bus/dlq.json`
- **PostgresStore**: `dead_letters` table

### Programmatic

```python
rt = Runtime()
dlq = rt.bus.dlq
print(dlq.count)
for record in dlq.records:
    print(record.event.event_type, record.error)
dlq.clear()
```

---

## Migrations

The migration engine applies pending schema changes on startup (auto-migrate enabled by default).

```bash
# Run pending migrations manually
underwrite migrate

# Check applied versions (Postgres)
psql $DATABASE_URL -c "SELECT * FROM migrations ORDER BY version;"
```

### Migration Plan

Current migrations (defined in `__migrate__.py`):

| Version | Description |
|---------|-------------|
| 1 | Initial store schema — key-value table, migrations table |
| 2 | Dead-letter queue table |
| 3 | Metrics snapshot table |

### Manual Rollback

```sql
-- Rollback version 3
DROP TABLE IF EXISTS metrics_snapshots;
DELETE FROM migrations WHERE version = 3;

-- Rollback version 2
DROP TABLE IF EXISTS dead_letters;
DELETE FROM migrations WHERE version = 2;
```

After rollback, `underwrite migrate` re-applies the migration.

---

## Indian Regulatory Operations

### NPA / SMA Monitoring

The platform tracks asset quality per RBI Master Circular on Income Recognition and Asset Classification (IRAC):

| Classification | Trigger | Event | Action |
|---|---|---|---|
| SMA-0 | 30 days past due | `sma.classified` | Alert relationship manager |
| SMA-1 | 60 days past due | `sma.classified` | Initiate collection |
| SMA-2 | 90 days past due | `sma.classified` | Prepare NPA report |
| NPA (Substandard) | 91-180 days | `npa.bucket.changed` | Provision at 15%, suspend income recognition |
| NPA (Doubtful) | 181-360 days | `npa.bucket.changed` | Provision at 25% (secured) |
| NPA (Loss) | >360 days | `npa.bucket.changed` | Provision at 100% |
| DLG Trigger | 120+ days | `npa.dlg.triggered` | Invoke default loss guarantee |

Monitor NPA ratios:

```bash
# Check current NPA classification counts
underwrite health | grep npa

# Expected output:
# service:npa — events_handled=42 sma0=5 sma1=2 sma2=1 npa_substandard=1
```

### Pricing Compliance Monitoring

Monitor that all loans fall within RBI-mandated rate caps:

```bash
underwrite metrics | grep -E "pricing|caps|penal"
```

Key metrics:
- `pricing.rate_caps` — count of rate cap applications
- `pricing.penal_interest` — penal interest assessments (should be ≤24% p.a.)
- `pricing.foreclosure` — foreclosure charge computations (0% for personal/home loans)

### Consent Audit Trail

All consent lifecycle events are recorded in the audit ledger:

```bash
# Query consent events (requires store inspection)
underwrite dlq | grep consent
```

Monitor consent expiry and withdrawal rates to ensure DPDPA compliance.

### DSR Fulfillment SLA

The platform tracks DSR response times. If a DSR exceeds 30 days:

1. `dsr.fulfilled` is not emitted — check `underwrite dlq` for pending requests
2. Escalate via `grievance.logged` event
3. Manually verify DPO notification (configured via `dpdpa.dsr.dpo_email`)

### Breach Detection

When `breach.detected` fires:

1. Identify scope via audit log: `underwrite health` and check store
2. Notify Data Protection Board within 72 hours (configurable)
3. Record breach closure via `breach.closed` event
4. Document in breach register

### RBI Reporting Schedule

| Report | Frequency | Data Source | Notes |
|--------|-----------|-------------|-------|
| NPA classification | Monthly | `npa.bucket.changed` events | RBI return on asset quality |
| Capital adequacy | Quarterly | Store aggregation | Leverage ratio monitoring |
| Interest rate disclosure | Monthly | Pricing service | Rate cap compliance report |
| KFS issuance log | Daily | KFS service | Cooling-off period tracking |
| Consent register | Monthly | Consent service | DPDPA compliance audit |
| Grievance register | Monthly | DSR service | DPDPA Section 13 compliance |
| Credit bureau data submission | Weekly | Credit bureau service | CIBIL/Experian/Equifax data refresh |

---

## Monitoring

### Health

```bash
underwrite health
```

HTTP health endpoints (requires `underwrite serve`):

| Endpoint | Path |
|----------|------|
| Liveness probe | `GET /healthz` |
| Readiness probe | `GET /readyz` |
| Full status | `GET /v1/health` |
| Legacy | `GET /health` |

### Metrics

```bash
underwrite metrics
```

Counters: `events.emitted`, `events.handled`, `events.failed`, `store.corruption`, `store.io_error`, `authz.failures`

Timers: `handle.duration` (per-service, per-event-type with count/avg/min/max)

HTTP: `GET /v1/metrics` returns Prometheus text format (requires `underwrite[serve]`).

### Logging

Configure via environment:

```bash
export UNDERWRITE_LOG_LEVEL=DEBUG
export UNDERWRITE_LOG_FORMAT=json
```

JSON format includes `timestamp`, `level`, `logger`, `message`, `module`, `line`, and optional `correlation_id`, `trace_id`, and `exception`. Sensitive fields (SSN, PAN, tokens, passwords) are automatically redacted.

### Tracing

OpenTelemetry distributed tracing:

```json
{
  "tracing": {
    "enabled": true,
    "exporter": "otlp"
  }
}
```

Requires `underwrite[otlp]` extra. Console exporter is also available for development.

---

## Backup

### FileStore Backup

Data is stored as individual JSON files in `data/`:

```bash
# Backup
tar czf underwrite-data-$(date +%Y%m%d).tar.gz data/

# Restore
tar xzf underwrite-data-20260608.tar.gz
```

Keys map to file paths: `saga:<id>` → `data/saga/<id>.json`.

### PostgresStore Backup

```bash
pg_dump $DATABASE_URL -t store -t migrations -t dead_letters -t metrics_snapshots > underwrite-backup.sql
```

---

## Recovery

### Saga Replay

Sagas that were interrupted by a crash can be replayed:

```python
from underwrite.__runtime__ import Runtime
rt = Runtime()
success = rt.replay_saga("saga-id-here")
```

`replay_saga()` finds the next unexecuted step after the last completed one and executes all remaining steps. Idempotency keys ensure no step is executed twice.

Saga status values: `started` → `completed` (success), or `compensating` → `rolled_back` (failure).

### DLQ Replay

After fixing the root cause (e.g., misconfiguration, missing env var), replay failed events:

```bash
underwrite dlq --replay
```

### Service Restart

Manually restart a failing service via the Runtime:

```python
rt.restart_failing_services()
```

---

## Incident Response

### 1. Check System Health

```bash
underwrite health
```

If degraded, check individual checks: `bus`, `store`, `service:<name>`, `supervisor`.

### 2. Check Dead Letter Queue

```bash
underwrite dlq
```

Look for patterns: all errors from one service, rate limiting, circuit open.

### 3. Check Logs

```bash
UNDERWRITE_LOG_LEVEL=DEBUG underwrite run <service>
```

With JSON logging:

```bash
underwrite serve --port 8080 | jq 'select(.level == "ERROR")'
```

### 4. Check Circuit Breakers

```bash
underwrite health | grep circuit
```

If circuits are open, wait for automatic recovery (15–60s depending on component).

### 5. Common Recovery Actions

| Issue | Action |
|-------|--------|
| Circuit breaker open | Wait for cooldown, or check store connectivity |
| DLQ accumulating | Fix handler error, then `underwrite dlq --replay` |
| Service crash-looping | Check logs, increase `max_restarts` or disable `auto_restart` |
| Saga stuck in `started` | `rt.replay_saga(id)` to retry |
| Migration failed | `SELECT * FROM migrations`, rollback failed version, fix and re-migrate |
| Store connection lost | Check DB endpoint, credentials, network policy |
| Signature verification failures | Check authz policy file and service identities |

---

## CLI Command Reference

| Command | Description |
|---------|-------------|
| `underwrite init [path]` | Create default config file |
| `underwrite run <service>...` | Start services in foreground |
| `underwrite serve` | Start HTTP daemon with health/metrics endpoints |
| `underwrite list` | List all available services |
| `underwrite health` | Show health status |
| `underwrite metrics` | Show metrics snapshot |
| `underwrite dlq` | Show dead-letter queue |
| `underwrite dlq --replay` | Replay dead-letter events |
| `underwrite migrate` | Run pending migrations |
| `underwrite identity <service>` | Generate Ed25519 identity for a service |

---

## Supported Plugins and Extras

Install extras with `pip install underwrite[<extra>]`:

| Extra | Provides |
|-------|----------|
| `serve` | FastAPI + uvicorn HTTP server |
| `postgres` | PostgreSQL store backend |
| `otlp` | OpenTelemetry distributed tracing |
| `risk` | NumPy + scikit-learn for risk scoring |
| `vault` | HashiCorp Vault secrets backend |
| `aws` | AWS Secrets Manager / S3 / SQS backends |
| `gcs` | Google Cloud Storage backend |
| `dev` | Pytest, ruff, mypy, bandit, testcontainers |
| `mutation` | Mutation testing (mutmut) |
| `security` | Bandit + pip-audit |
| `all` | All extras combined |

### Prometheus

When `serve` extra is installed, `GET /v1/metrics` exposes runtime and service metrics in Prometheus text format at `text/plain; version=0.0.4`. FastAPI can also be instrumented with OpenTelemetry via `opentelemetry-instrumentation-fastapi`.
