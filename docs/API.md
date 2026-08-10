# API Reference — underwrite

## Python API

All public API symbols are importable from the `underwrite` top-level package. Full list at `underwrite/init.py:44`.

### Runtime

```python
from underwrite import Runtime
from underwrite.config import Configuration

config = Configuration.load("underwrite.json")
rt = Runtime(config)

# Lifecycle
rt.start(["mechanism", "audit", "risk"])  # starts bus, registers & wires services
rt.stop()  # stops all services, bus, metrics loop
rt.get("mechanism")  # → NanoService | None
rt.services  # → dict[str, NanoService]

# Event publishing
rt.publish(event_type="loan.originated", payload={...}, correlation_id="...")
# → str (event_id)

# Async variant for FastAPI/ASGI contexts
await rt.async_publish(event_type="...", payload={...})

# Crash recovery
rt.replay_saga("saga-uuid")  # → bool

# Runtime as context manager
with Runtime(config) as rt:
    rt.start(["mechanism"])
```

| Method | Returns | Description |
|---|---|---|
| `start(names)` | `None` | Registers, wires, and starts services; runs migrations |
| `stop()` | `None` | Graceful shutdown of all subsystems |
| `publish(event_type, payload, correlation_id)` | `str` | Publishes domain event, returns `event_id` |
| `async_publish(event_type, payload, correlation_id)` | `str` | Async variant for ASGI contexts |
| `register(service_name)` | `NanoService` | Instantiates a service by name |
| `wire(service_name)` | `None` | Subscribes service to its event types |
| `get(service_name)` | `NanoService | None` | Returns registered service |
| `replay_saga(saga_id)` | `bool` | Replays incomplete saga for crash recovery |

Properties: `bus`, `store`, `health`, `metrics`, `authz`, `tracer`, `saga`, `supervisor`, `secrets`.

### Configuration

```python
from underwrite.config import Configuration

# Loading
config = Configuration.load()  # auto-discover: underwrite.json → config.{env}.json
config = Configuration.load("path/to/config.json")

# Default
default = Configuration.default()  # store backend = "filesystem", all services disabled

# Save
config.save("underwrite.json")

# Access
config.bus.backend  # "local" | "sqs" | "modal"
config.store.backend  # "memory" | "filesystem" | "postgres"
config.store.dsn  # postgres DSN
config.services["risk"].enabled  # bool
config.services["mechanism"].priority  # int
config.logging.level  # "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
config.logging.log_format  # "text" | "json"
config.authz.enabled  # bool
config.metrics.enabled  # bool
config.tracing.enabled  # bool
config.saga.enabled  # bool
config.data_dir  # "./data"
config.fee.schedules  # {"late_payment": 25.0, ...}
config.governance.param_defaults  # {"protocol_rate": 0.10, ...}
config.audit.max_ledger  # 100000

# Env overrides
# All config keys can be set via UNDERWRITE_* env vars:
#   UNDERWRITE_STORE_BACKEND=postgres
#   UNDERWRITE_STORE_DSN=postgresql://...
#   UNDERWRITE_LOG_LEVEL=DEBUG
#   UNDERWRITE_AUTHZ_ENABLED=false
# (full list in config.py:403)
```

### NanoService

```python
from underwrite.services import NanoService


class MyService(NanoService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.subscribe("my.event.type")

    def handle(self, event: Event) -> None:
        self.emit("response.event", {"key": "value"})


# Lifecycle
svc.start()  # begins processing events
svc.stop()  # stops, unsubscribes all handlers

# Event emission
svc.emit(event_type="my.event", payload={...}, correlation_id="...")
# → Event (auto-signed, published to bus)

# Subscriptions
svc.subscribe("some.event.type")  # register handler

# State
svc.store  # → Store
svc.service_id  # → str
svc.is_running  # → bool
svc.bus  # → EventBus
svc.metrics_collector  # → MetricsCollector | None
svc.state_lock  # → threading.RLock
svc.validator  # → PayloadValidator
svc.safe_store_get(key, default)  # → Any | None
svc.safe_store_set(key, value)  # → bool
svc.sign_event(payload_str)  # → str (signature)
```

All 28 services extend `NanoService`. Stateful services extend `StatefulService` which adds a `state_lock` and `store_repo()` / `batched_repo()` factory helpers for typed persistence.

### Event & EventType

```python
from underwrite import Event, EventType

# Create an event
event = Event(
    event_type="loan.originated",
    source="mechanism",
    payload={"borrower": "alice", "principal": 50000},
    correlation_id="corr-123",
)

# Event fields (frozen dataclass)
event.event_id  # "uuid-string"
event.event_type  # "loan.originated"
event.source  # "mechanism"
event.source_key  # base64 Ed25519 public key
event.timestamp  # ISO-8601 UTC
event.payload  # dict
event.correlation_id  # uuid string
event.signature  # Ed25519 signature
event.trace_id  # distributed tracing ID
event.parent_span_id  # parent span for nesting

# Event type enum
EventType.SEED_ADDED  # "seed.added"
EventType.USER_ADDED  # "user.added"
EventType.LOAN_ORIGINATED  # "loan.originated"
EventType.REPAID  # "repaid"
EventType.DEFAULT_OCCURRED  # "default.occurred"
EventType.REVOKED  # "revoked"
EventType.QUOTE  # "quote"
EventType.QUOTE_CALCULATED  # "quote.calculated"
EventType.PRICING_REQUEST  # "pricing.request"
EventType.PRICING_COMPUTED  # "pricing.computed"
EventType.PENAL_INTEREST_ASSESSED  # "penal_interest.assessed"
EventType.FORECLOSURE_COMPUTED  # "foreclosure.computed"
EventType.PREPAYMENT_REQUEST  # "prepayment.request"
EventType.PREPAYMENT_PROCESSED  # "prepayment.processed"
EventType.KYC_VERIFIED  # "kyc.verified"
EventType.KYC_REJECTED  # "kyc.rejected"
EventType.AML_CLEARED  # "aml.cleared"
EventType.AML_FROZEN  # "aml.frozen"
EventType.CKYC_VERIFY  # "ckyc.verify"
EventType.CKYC_VERIFIED  # "ckyc.verified"
EventType.CKYC_REJECTED  # "ckyc.rejected"
EventType.CREDIT_BUREAU_CHECK  # "credit_bureau.check"
EventType.CREDIT_BUREAU_CHECKED  # "credit_bureau.checked"
EventType.CREDIT_BUREAU_CHECK_FAILED  # "credit_bureau.check_failed"
EventType.CONSENT_RECORDED  # "consent.recorded"
EventType.CONSENT_WITHDRAWN  # "consent.withdrawn"
EventType.CONSENT_EXPIRED  # "consent.expired"
EventType.DSR_REQUEST  # "dsr.request"
EventType.DSR_REQUESTED  # "dsr.requested"
EventType.DSR_FULFILLED  # "dsr.fulfilled"
EventType.DSR_REJECTED  # "dsr.rejected"
EventType.KFS_GENERATE  # "kfs.generate"
EventType.KFS_GENERATED  # "kfs.generated"
EventType.BREACH_DETECTED  # "breach.detected"
EventType.BREACH_NOTIFIED  # "breach.notified"
EventType.BREACH_CLOSED  # "breach.closed"
EventType.GRIEVANCE_LOGGED  # "grievance.logged"
EventType.GRIEVANCE_RESOLVED  # "grievance.resolved"
EventType.DATA_PURGED  # "data.purged"
EventType.DATA_ARCHIVED  # "data.archived"
EventType.PROVISIONING_COMPUTED  # "provisioning.computed"
EventType.SMA_CLASSIFIED  # "sma.classified"
EventType.INCOME_RECOGNITION_SUSPENDED  # "income_recognition.suspended"
EventType.RAZORPAY_ORDER_CREATE  # "razorpay.order.create"
EventType.RAZORPAY_ORDER_CREATED  # "razorpay.order.created"
EventType.RAZORPAY_PAYMENT_CAPTURED  # "razorpay.payment.captured"
EventType.RAZORPAY_PAYMENT_FAILED  # "razorpay.payment.failed"
EventType.RAZORPAY_PAYMENT_REFUNDED  # "razorpay.payment.refunded"
EventType.RAZORPAY_SUBSCRIBE  # "razorpay.subscribe"
EventType.RAZORPAY_SUBSCRIPTION_CREATED  # "razorpay.subscription.created"
EventType.RAZORPAY_SUBSCRIPTION_CHARGED  # "razorpay.subscription.charged"
EventType.RAZORPAY_SUBSCRIPTION_FAILED  # "razorpay.subscription.failed"
EventType.RAZORPAY_MANDATE_ACTIVE  # "razorpay.mandate.active"
EventType.RAZORPAY_MANDATE_INACTIVE  # "razorpay.mandate.inactive"
EventType.RAZORPAY_WEBHOOK_RECEIVED  # "razorpay.webhook.received"
EventType.FRAUD_ALERT  # "fraud.alert"
EventType.WASH_FLAG  # "fraud.wash.flag"
EventType.VELOCITY_FLAG  # "fraud.velocity.flag"
EventType.RISK_SCORED  # "risk.scored"
EventType.RISK_EARLY_WARNING  # "risk.early_warning"
EventType.NPA_BUCKET_CHANGED  # "npa.bucket.changed"
EventType.DLG_TRIGGERED  # "npa.dlg.triggered"
EventType.COLLATERAL_MARKED  # "collateral.marked"
EventType.COLLATERAL_LIQUIDATED  # "collateral.liquidated"
EventType.GOVERNANCE_PROPOSAL  # "governance.proposal"
EventType.GOVERNANCE_EXECUTED  # "governance.executed"
EventType.RECOVERY_STARTED  # "recovery.started"
EventType.RECOVERY_COMPLETED  # "recovery.completed"
EventType.IDENTITY_REGISTERED  # "identity.registered"
EventType.IDENTITY_ROTATED  # "identity.rotated"
EventType.NOTIFICATION_SENT  # "notification.sent"
EventType.REPORT_GENERATED  # "report.generated"
EventType.UNDERWRITER_APPROVED  # "underwriter.approved"
EventType.UNDERWRITER_REJECTED  # "underwriter.rejected"
EventType.UNDERWRITER_ESCALATED  # "underwriter.escalated"
EventType.UNDERWRITER_CONDITIONAL_APPROVED  # "underwriter.conditional_approved"
EventType.UNDERWRITER_REVIEW  # "underwriter.review"
EventType.UNDERWRITE_REQUEST  # "underwrite.request"
EventType.UNDERWRITE_RULE_VIOLATED  # "underwrite.rule.violated"
EventType.DOCUMENT_GENERATED  # "document.generated"
EventType.DISBURSEMENT_PROCESSED  # "disbursement.processed"
EventType.COLLECTION_UPDATED  # "collection.updated"
EventType.SETTLEMENT_COMPLETED  # "settlement.completed"
EventType.ORIGINATION_CREATED  # "origination.created"
EventType.ORIGINATION_SUBMITTED  # "origination.submitted"
EventType.SERVICING_STARTED  # "servicing.started"
EventType.PAYMENT_RECEIVED  # "payment.received"
EventType.PAYMENT_DUE  # "payment.due"
EventType.PAYMENT_OVERDUE  # "payment.overdue"
EventType.FEE_ASSESSED  # "fee.assessed"
EventType.STATEMENT_GENERATED  # "statement.generated"
EventType.COMMUNICATION_SENT  # "communication.sent"
EventType.WORKFLOW_STARTED  # "workflow.started"
EventType.WORKFLOW_COMPLETED  # "workflow.completed"
EventType.DECISION_MADE  # "decision.made"
EventType.SAGA_STARTED  # "saga.started"
EventType.SAGA_COMPLETED  # "saga.completed"
EventType.SAGA_ROLLED_BACK  # "saga.rolled_back"
EventType.SAGA_COMPENSATE  # "saga.compensate"
EventType.DUPLICATE_DROPPED  # "idempotency.duplicate_dropped"
EventType.UNDERWRITE_REQUEST  # "underwrite.request"
EventType.MECHANISM_REJECTED  # "mechanism.rejected"
EventType.GRAPH_PATH  # "graph_path"
EventType.GRAPH_PATH_RESULT  # "graph_path_result"
EventType.GRAPH_CREDIT_LIMIT  # "graph_credit_limit"
EventType.GRAPH_CREDIT_LIMIT_RESULT  # "graph_credit_limit_result"
EventType.GRAPH_USERS  # "graph_users"
EventType.GRAPH_USERS_RESULT  # "graph_users_result"
# + `*` commands (identity.register, identity.rotate, fee.assess, etc.)
# Full 105+ type registry in underwrite/events.py:62
```

Convention: events ending in `.past_tense` (e.g. `loan.originated`) are **notifications** of something that happened. Events ending in a bare noun (e.g. `fee.assess`, `payment.receive`) are **commands** requesting an action.

### Store

```python
from underwrite import Store, MemoryStore, FileStore

# Abstract interface
store.get("key")  # → Any | None
store.set("key", value)  # → None
store.delete("key")  # → bool (True if existed)
store.exists("key")  # → bool
store.keys(pattern="substring")  # → list[str]
store.keys(pattern="prefix:*", limit=100, offset=0)

# Concrete implementations
MemoryStore(max_entries=10000)  # in-memory, LRU eviction
FileStore(data_dir="./data")  # JSON files, atomic writes, fsync
PostgresStore(dsn="...", table="store", pool_size=5)
CQRSStore(write_store, read_store)  # read/write separation

# Store features
file_store = FileStore(
    data_dir="./data",
    operation_timeout=5.0,  # timeout per I/O op
    use_circuit_breaker=True,  # 3 fails → open 30s
    fsync=True,  # safe but slower
)
```

### Identity

```python
from underwrite.identity import Identity

# Create
identity = Identity.create("mechanism")
identity = Identity.create("mechanism", encryption_passphrase="s3cret")
identity = Identity.create("mechanism", private_key_pem="...")

# Sign & Verify
sig = identity.sign("payload-string")
ok = identity.verify("payload-string", sig)  # → bool

# Persist
pem = identity.to_pem()  # PEM-encoded private key
identity.persist(secrets_manager)  # store through backend
```

### AccessControl

```python
from underwrite.authz import AccessControl

acl = AccessControl()

# Policy rules
acl.allow("mechanism", "publish:loan.*")  # allow wildcard
acl.deny("fraud", "publish:governance.*")  # deny wildcard
acl.trust("mechanism", base64_public_key)  # register trusted key

# Checks
acl.check_publish("mechanism", "loan.originated")  # → bool
acl.check_subscribe("audit", "loan.originated")  # → bool

# Assertions (raises AuthzError)
acl.assert_publish("mechanism", "loan.originated")
acl.assert_subscribe("audit", "loan.originated")
acl.assert_verified(event)

# Trust management
acl.revoke_trust("mechanism")  # remove trusted key
```

Default policy when no file is loaded: `allow("*", "*")` (all services, all resources). Load from JSON policy file:

```json
{
  "allow": [{"subject": "mechanism", "resource": "publish:seed.*"}],
  "deny":  [{"subject": "fraud", "resource": "publish:governance.*"}]
}
```

### SagaOrchestrator

```python
from underwrite.saga import SagaOrchestrator, SagaStep

saga = SagaOrchestrator(store=store)

# Define steps
steps = [
    SagaStep(
        name="originate",
        forward_event_type="mechanism",
        forward_payload={"command": "originate", "borrower": "alice", ...},
        compensate_event_type="mechanism",
        compensate_payload={"command": "revoke", ...},
    ),
]

# Execute
saga_id = saga.start_saga("loan_origination", steps)
saga.execute_step(saga_id, 0)         # single step
saga.execute_all(saga_id)             # all steps sequentially

# Replay (crash recovery)
saga.replay_saga(saga_id)

# Inspect
saga_obj = saga.get_saga(saga_id)
saga_obj.status          # "started" | "completed" | "rolled_back" | "compensating"
saga_obj.completed_steps # [0, 1, ...]
saga_obj.error           # error description if rolled back
```

Uses store-backed idempotency key per step (`saga_step:{saga_id}:{step_index}`) so replay is safe after crashes. On any step failure, all prior completed steps are rolled back in reverse order via compensation events.

### CircuitBreaker

```python
from underwrite.circuit import CircuitBreaker, RetryPolicy

cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="filestore")

# Protected call
result = cb.call(my_function, arg1, arg2)
# → my_function return value
# → raises CircuitBreakerOpenError if circuit is open

# Retry policy
retry = RetryPolicy(max_retries=3, base_delay=0.1, max_delay=5.0)
result = retry.execute(my_function, arg1, arg2)
```

States: `CLOSED` → `OPEN` (after `failure_threshold` consecutive failures) → `HALF_OPEN` (after `recovery_timeout`). Single success in `HALF_OPEN` returns to `CLOSED`.

### Tracer

```python
from underwrite.tracer import Tracer, ConsoleSpanExporter, OtlpSpanExporter

tracer = Tracer(service_id="mechanism")
tracer = Tracer(service_id="mechanism", exporter=ConsoleSpanExporter())

# Manual spans
span = tracer.start_span("handle.loan.originated", trace_id="...", tags={"borrower": "alice"})
# ... do work ...
tracer.end_span(span, error="")  # error string if failed

# Context manager (preferred)
with tracer.trace("handle.loan.originated", tags={"borrower": "alice"}) as span:
    # ... do work ...

tracer.spans  # → list[Span] snapshot
```

Span data: `trace_id`, `span_id`, `parent_span_id`, `service_id`, `operation`, `start_ms`, `end_ms`, `tags`, `error`.

Exporters: `ConsoleSpanExporter` (stdout), `OtlpSpanExporter` (OpenTelemetry gRPC). Configure via `Configuration.tracing.exporter`.

### MetricsCollector

```python
from underwrite.metrics import MetricsCollector

mc = MetricsCollector(max_metrics=10000)

mc.increment("events.handled", {"service": "mechanism", "event_type": "loan.originated"})
mc.increment("events.handled", delta=5)  # increment by 5

mc.gauge("connections.active", value=42, tags={"pool": "main"})

mc.timer("handle.duration", duration_ms=12.3, tags={"service": "mechanism"})

# Context manager timer
with mc.time("process.duration", tags={"operation": "originate"}) as _:
    # ... timed work ...

# Snapshot
snap = mc.snapshot()
snap["counters"]   # {"name:tag=val": {"value": 1, "tags": {...}}}
snap["timers"]     # {"name:...": {"count": 5, "avg_ms": 12.3, "min_ms": 1.0, "max_ms": 50.0}}
snap["gauges"]     # {"name:...": {"value": 42, "tags": {...}}}

mc.reset()         # clear all metrics
```

### Exceptions

```python
from underwrite.exceptions import (
    UnderwriteError,  # base
    ConfigurationError,  # invalid config
    ServiceNotFoundError,  # unknown service name
    IdentityError,  # key management failure
    BusError,  # event bus failure
    StoreError,  # store persistence failure
    ProtocolError,  # protocol violation
    UnknownUserError,  # missing graph user
    InvariantViolationError,  # state invariant broken
    InfeasibleOperationError,  # e.g. insufficient credit
    AuthzError,  # access control denial
    RateLimitError,  # rate limit exceeded
    MigrationError,  # schema migration failure
    SagaError,  # saga step failure
    CircuitBreakerOpenError,  # circuit is open
)
```

---

## HTTP API

Served via FastAPI. Start with `underwrite serve` or programmatically via `serve.py`.

### Starting the Server

```bash
# CLI
underwrite serve --host 0.0.0.0 --port 8080 --services mechanism,audit,risk
underwrite serve --require-auth                                       # requires UNDERWRITE_API_TOKEN
underwrite serve --rate-limit 200 --shutdown-timeout 60
```

```python
# Programmatic
from underwrite.serve import create_app
from underwrite.runtime import Runtime

rt = Runtime()
app = create_app(
    runtime=rt,
    services="mechanism,audit,risk",
    rate_limit=100,
    require_auth=False,
    api_token="",
    shutdown_timeout=30,
)
```

### Authentication

When `--require-auth` is used (or `UNDERWRITE_API_TOKEN` is set), every request must include:

```
Authorization: Bearer <token>
```

The token is compared using `hmac.compare_digest` (constant-time). Without auth configured, the server logs a warning on startup. In production, always set `UNDERWRITE_API_TOKEN`.

### Endpoints

#### `GET /healthz`
Kubernetes liveness probe.

```
> GET /healthz
< 200 OK
< {"status": "healthy", "ok": true, "checks": {...}, "checked_at": "..."}
```

Returns 503 if any subsystem is unhealthy.

#### `GET /readyz`
Kubernetes readiness probe. Identical response to `/healthz`.

#### `GET /v1/health`
Full system health, aggregated from all registered subsystems (bus, store, services, metrics, tracer, saga, DLQ, supervisor).

```
> GET /v1/health
< 200 OK
< {
    "status": "healthy",
    "ok": true,
    "checks": {
        "bus": {"ok": true, "subscribers": 12, "dlq_count": 0},
        "store": {"ok": true},
        "services": {"ok": true, "running": ["mechanism", "audit", "risk"]},
        "metrics": {"ok": true},
        "dlq": {"ok": true, "dead_letter_count": 0},
        "service:mechanism": {"ok": true, "service_id": "mechanism", "events_handled": 142, ...},
        "service:audit": {"ok": true, ...}
    },
    "checked_at": "2025-06-08T12:00:00+00:00"
}
```

#### `GET /v1/metrics`
Prometheus text-format metrics. Requires `underwrite[serve]`.

```
> GET /v1/metrics
< 200 OK
< Content-Type: text/plain; version=0.0.4
<
< # HELP underwrite_events_handled Total events handled
< # TYPE underwrite_events_handled counter
< underwrite_events_handled{service="mechanism",event_type="loan.originated"} 42
```

Returns 501 if the prometheus extra is not installed.

#### `POST /v1/publish`
Publish a domain event. Fire-and-forget (returns 202 on acceptance).

```
> POST /v1/publish
> Content-Type: application/json
> Authorization: Bearer <token>          # if auth enabled
> X-Request-ID: custom-trace-id          # optional, for distributed tracing
>
> {
    "event_type": "loan.originated",
    "payload": {
        "borrower": "alice",
        "principal": 50000,
        "term": 12,
        "default_probability": 0.15,
        "protocol_rate": 0.10,
        "max_delegation_rate": 0.05
    },
    "correlation_id": "corr-abc-123"
}

< 202 Accepted
< {
    "status": "accepted"
}
< X-Request-ID: <echoed-or-generated>
```

**Error responses:**

```json
// 400 — event_type missing or invalid
{"error": "event_type is required", "status_code": 400, "request_id": "..."}

// 400 — protocol violation
{"error": "invalid request", "status_code": 400, "request_id": "..."}

// 401 — missing/invalid bearer token
{"error": "unauthorized", "status_code": 401, "request_id": "..."}

// 413 — request body too large (limit: 1 MB)
{"error": "request body too large", "status_code": 413, "request_id": "..."}

// 429 — rate limit exceeded
{"error": "rate limit exceeded", "status_code": 429, "request_id": "..."}

// 500 — internal server error
{"error": "internal server error", "status_code": 500, "request_id": "..."}

// 501 — feature not available (e.g. prometheus without [serve])
{"error": "prometheus export not available; install underwrite[serve]", "status_code": 501}
```

Every response includes an `X-Request-ID` header for distributed tracing correlation.

### Rate Limiting

Token-bucket algorithm applied globally. Default: 100 requests/second. Configurable via `--rate-limit` CLI flag or `rate_limit` parameter in `create_app()`. A 429 is returned when the bucket is empty.

### Error Handling

All error responses follow the same envelope:

```json
{
    "error": "description",
    "status_code": 4xx,
    "request_id": "uuid"
}
```

No stack traces are leaked in production responses. Internal errors are logged via the underwrite logger (structured JSON in production mode).

### Middleware Stack

1. **Body size check** — rejects requests > 1 MB before parsing
2. **X-Request-ID** — echoes or generates a request ID on every response
3. **Auth + Rate Limiter** — bearer token validation (constant-time HMAC) followed by token-bucket rate limiting
4. **OpenTelemetry** — optional FastAPI instrumentation when `opentelemetry-instrumentation-fastapi` is installed

---

## CLI API

Entry point: `underwrite` (Typer app, defined in `underwrite/cli.py`).

### `underwrite init [PATH]`

Generate a default configuration file (default: `./underwrite.json`).

```bash
underwrite init
# Configuration written to underwrite.json

underwrite init /etc/underwrite/prod.json
```

Fails if the target file already exists.

### `underwrite run <service>...`

Start one or more nano services.

```bash
underwrite run mechanism audit risk fraud compliance
underwrite run mechanism                    # single service
```

Validates service names against known list. Uses `SIGTERM` handler for graceful shutdown. Blocking — press Ctrl+C to stop.

### `underwrite list`

List all 28 registered nano services.

```bash
$ underwrite list
Available nano services:
  - mechanism
  - audit
  - quote
  - risk
  - fraud
  - compliance
  - npa
  - collateral
  - recovery
  - governance
  - graph
  - identity
  - notification
  - reporting
  - underwriter
  - pricing
  - document
  - disbursement
  - collection
  - settlement
  - origination
  - servicing
  - payment
  - communication
  - workflow
  - decision
  - fee
  - statement
```

### `underwrite identity <service>`

Generate Ed25519 identity for a service.

```bash
$ underwrite identity mechanism
Identity for: mechanism
  Public key:  <base64-encoded public key>
  Private key: (stored only in memory / TPM — not printable)
```

### `underwrite health`

Show aggregated system health.

```bash
$ underwrite health
Status: healthy
OK: True
Checks:
  [OK] bus — subscribers=8 dlq_count=0
  [OK] store
  [OK] services — running=['mechanism', 'audit']
  [OK] metrics
  [OK] dlq — dead_letter_count=0
  [OK] service:mechanism — events_handled=142
  [OK] service:audit — events_handled=142

Exit code 0 if healthy, 1 if degraded.
```

### `underwrite dlq [--replay] [--max N]`

Inspect or replay the dead-letter queue.

```bash
# Show recent DLQ entries
$ underwrite dlq
Dead-letter queue: 3 entries
  [1710000000.0] subscriber_abc: loan.originated — ProtocolError: insufficient credit

# Replay all
$ underwrite dlq --replay
Replayed 3 dead-letter event(s)

# Replay up to 10
$ underwrite dlq --replay --max 10
```

### `underwrite metrics`

Show metrics snapshot.

```bash
$ underwrite metrics
Counters:
  events.emitted:service=mechanism:event_type=seed.added: 5
  events.handled:service=audit:event_type=seed.added: 5
Timers:
  handle.duration:service=mechanism:event_type=seed.added: count=5 avg=2.1ms min=0.5ms max=4.2ms
```

### `underwrite migrate`

Apply pending store migrations.

```bash
$ underwrite migrate
Migrations applied
```

### `underwrite serve`

Start the HTTP daemon.

```bash
underwrite serve --port 8080
underwrite serve --require-auth --services mechanism,audit,risk,fraud
underwrite serve --host 0.0.0.0 --port 443 --rate-limit 500 --shutdown-timeout 60
```

Requires `uvicorn` (install via `pip install underwrite[serve]`).
