# Architecture — underwrite

## Overview

underwrite is an **event-driven nano-service platform** for delegated unsecured lending underwriting. 28 independent services communicate over a shared in-process event bus, each extending the `NanoService` abstract base class.

```mermaid
graph TB
    subgraph External["External"]
        CLI["CLI (typer)"]
        HTTP["HTTP API (FastAPI)"]
    end

    subgraph Runtime["Runtime (runtime.py)"]
        CFG["Configuration"]
        BUS["EventBus"]
        STORE["Store"]
        AUTHZ["AccessControl"]
        TRACER["Tracer"]
        METRICS["MetricsCollector"]
        SAGA["SagaOrchestrator"]
        SUP["ServiceSupervisor"]
    end

    subgraph Services["28 NanoServices"]
        MECH["MechanismService"]
        RISK["RiskService"]
        FRAUD["FraudService"]
        AUDIT["AuditService"]
        OTHER["... 24 more"]
    end

    CLI --> CFG
    HTTP --> BUS
    BUS --> Services
    Services --> STORE
    Services --> AUTHZ
    Services --> TRACER
    Services --> METRICS
    Services --> SAGA
    SAGA --> BUS
    SUP --> Services
```

## Layers

| Layer | Module | Responsibility |
|-------|--------|---------------|
| **HTTP Gateway** | `serve.py` | FastAPI app, auth middleware, rate limiting, health/metrics endpoints |
| **CLI** | `cli.py` | Typer-based command interface (`run`, `list`, `health`, `dlq`, `metrics`) |
| **Runtime** | `runtime.py` | Service lifecycle, factory wiring, migration orchestration, health aggregation |
| **Event Bus** | `bus.py` | Publish/subscribe, dead-letter queue, rate limiter, idempotency guard |
| **State Store** | `store.py` | SQLite persistence (file or `:memory:`) |
| **Authz** | `authz.py` | Allow/deny policy evaluation, Ed25519 signature verification |
| **Identity** | `identity.py` | Ed25519 keypair creation, rotation, TTL management |
| **Saga** | `saga.py` | Multi-step transaction orchestration with compensating rollback |
| **Tracing** | `tracer.py` | Span creation, parent/child propagation, console/OTLP export |
| **Metrics** | `metrics.py` | Counters, timers, gauges, Prometheus-formatted export |
| **Circuit Breaker** | `circuit.py` | Failure isolation (CLOSED/OPEN/HALF_OPEN), exponential backoff retry |
| **Supervisor** | `supervisor.py` | Failure tracking, auto-restart with exponential backoff |
| **Secrets** | `secrets.py` | Secret retrieval (env vars, Vault, AWS Secrets Manager) |
| **Services** | `services/*/service.py` | Domain logic — 28 implementations |

## Event-Driven Communication

All nano-services communicate exclusively through typed domain events. Each event is an `Event` dataclass with:

- `event_id` — UUID v4
- `event_type` — string from the `EventType` enum (80+ values)
- `source` — emitting service ID
- `source_key` — Ed25519 public key
- `payload` — dict of domain data (max 1 MB, max 1000 keys)
- `signature` — Ed25519 signature over the canonical event content
- `correlation_id` — for tracing request chains
- `trace_id` / `parent_span_id` — distributed tracing context

```mermaid
sequenceDiagram
    participant A as Service A
    participant Bus as EventBus
    participant B as Service B
    participant C as Service C

    A->>Bus: emit("loan.originated", payload)
    Bus->>Bus: find subscribers for event_type
    Bus->>B: dispatch(event)
    Bus->>C: dispatch(event)
    Note over B: __dispatch → authz → idempotency → trace → handle()
    Note over C: __dispatch → authz → idempotency → trace → handle()
```

## NanoService Base Class

Every service extends `NanoService` (or `StatefulService`) and implements:

```python
class MyService(NanoService):
    def handle(self, event: Event) -> None:
        # Domain logic — called by __dispatch
        ...
        self.emit("downstream.event", result_payload)
```

The base class handles all cross-cutting concerns automatically:

```mermaid
flowchart LR
    subgraph Dispatch["__dispatch pipeline"]
        E["Event received"] --> A1{"Authz check"}
        A1 -->|fail| DROP["Drop (log warning)"]
        A1 -->|pass| I1{"Idempotent?"}
        I1 -->|duplicate| DROP
        I1 -->|new| T["Tracer.start_span()"]
        T --> M["Metrics.increment()"]
        M --> H["handle()"]
        H --> M2["Metrics.timer()"]
        M2 --> T2["Tracer.end_span()"]
        T2 --> SUP["Supervisor.record_success()"]
    end
```

## Service Wiring

Service-to-event subscriptions are declared in the `WIRING` dictionary (`handler.py`). For example:

| Event Type | Subscribers |
|-----------|-------------|
| `loan.originated` | audit, fraud, risk, npa, collateral, collection, servicing, payment, fee |
| `default.occurred` | audit, npa, collateral, recovery, settlement, workflow |
| `underwriter.approved` | audit, document, disbursement, workflow |
| `fraud.alert` | audit, notification, decision |

## Saga Orchestration

Multi-step distributed transactions use the Saga pattern:

```mermaid
flowchart LR
    subgraph Happy["Happy Path"]
        S1["Step 1: forward event"] --> S2["Step 2: forward event"]
        S2 --> S3["Step 3: forward event"]
        S3 --> DONE["✓ Completed"]
    end
    subgraph Rollback["Rollback"]
        S3x["Step 3 fails"] --> R2["Compensate Step 2"]
        R2 --> R1["Compensate Step 1"]
        R1 --> RB["↺ Rolled Back"]
    end
```

## State Persistence

The platform persists state through a single `Sqlite` backend
backed by the Python standard library `sqlite3`. A `:memory:`
path gives an ephemeral in-process database; any other path
creates a file-backed database with WAL journaling.

```mermaid
flowchart TB
    subgraph Stores["Store"]
        SQL["Sqlite<br/>file or :memory:, WAL, busy_timeout"]
    end
    subgraph Patterns["Usage Patterns"]
        KV["Key-Value: get/set/delete/exists"]
        MIG["migrate(): transactional schema updates"]
    end
```

## Security Architecture

Every emitted event is Ed25519-signed by the source service's `Identity`:

1. `NanoService.emit()` creates the event, serializes the payload, signs with `self.__identity.sign(to_sign)`
2. Downstream `__dispatch()` calls `self.__authz.assert_verified(event)` to verify the signature
3. `AccessControl` evaluates allow/deny policies (default-deny) for publish and subscribe operations
4. Ed25519 keys are rotated manually by generating a new `Identity.create(...)` and updating the runtime; rely on `AccessControl.set_replay_window(...)` to keep recent signatures verifiable

## Resilience

| Pattern | Mechanism | Configuration |
|---------|-----------|---------------|
| Circuit breaker | Per-store, trips after N failures | 3 failures, 15s recovery |
| Retry | Exponential backoff with jitter | 2 retries, 50ms base delay |
| Rate limiting | Token bucket per subscriber | 100 ops/s default |
| Dead letter queue | Bounded FIFO, optional Store persistence | 1000 max entries |
| Idempotency | (handler_id, event_id) dedup | Bounded per handler |
| Service supervisor | Auto-restart with backoff | 3 max restarts, 1s base backoff |

## Observability

| Concern | Mechanism | Export |
|---------|-----------|--------|
| Logging | stdlib logging, JSON formatter, PII redaction | stdout/stderr |
| Metrics | Counters, timers, gauges | /v1/metrics (Prometheus) |
| Tracing | Span lifecycle with parent/child | Console or OTLP/gRPC |
| Health | Named check registry | /healthz, /readyz, /v1/health |
