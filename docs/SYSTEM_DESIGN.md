# System Design — Underwrite Platform

> Runtime behavior, request lifecycle, data flow, and internal interactions of the unsecured lending underwriting nano-service platform.

---

## 1. Runtime Initialization Flow

Source: `underwrite/runtime.py`

```python
Runtime(config)             # or Runtime() loads defaults
  │
  ├─1. Configuration loaded from JSON file or defaults
  │    (underwrite/config.py → Configuration)
  │
  ├─2. Store created
  │    ├─ config.store.backend == "sqlite"    → Sqlite(path, busy_timeout)
  │    └─ config.store.backend == "memory"    → Sqlite(":memory:")
  │
  ├─3. (no separate read-store — CQRS is not supported in this revision)
  │
  ├─4. EventBus created
  │    └─ LocalBus(rate_limit, max_workers, max_futures, store)
  │
  ├─5. Optional subsystems created based on config
  │    ├─ Tracer            (tracing.enabled)
  │    ├─ MetricsCollector  (metrics.enabled)
  │    ├─ SecretsManager    (secrets.backend != "none")
  │    ├─ SagaOrchestrator  (saga.enabled)
  │    ├─ AccessControl     (authz.enabled)
  │    └─ ServiceSupervisor (recovery.auto_restart)
  │
  ├─6. Subsystem health checks registered
  │
  └─ Runtime.start(service_names)
       ├─ a. Run migrations             (auto_migrate)
       ├─ b. Start metrics export loop  (export_interval > 0)
       ├─ c. For each service:
       │     ├─ register(name)          → importlib import + instantiate
       │     ├─ wire(name)              → subscribe to WIRING event types
       │     └─ start()                 → set __running = True
       └─ d. bus.start()                → flush buffered events
```

---

## 2. Event Lifecycle

Source: `underwrite/events.py`, `underwrite/bus.py`, `underwrite/services/base.py`

```
External Trigger (CLI / HTTP POST /v1/publish / internal emit)
  │
  ▼
Event created [event_id (UUID), timestamp, event_type, payload,
               source, source_key, correlation_id, signature, trace_id]
  │
  ▼
EventBus.publish(event)
  │
  ├─ Buffer appended
  ├─ If bus running: flush() → for each subscriber:
  │     ├─ CircuitBreaker.allow_request(sid)?
  │     │    └─ NO → DLQ.put(event, "circuit_open", sid)
  │     ├─ RateLimiter.check(sub:sid)?
  │     │    └─ NO → DLQ.put(event, "rate_limited", sid)
  │     └─ Dispatch (sync or threadpool):
  │           │
  │           ▼
  │     NanoService.__dispatch(event)
  │       ├─ not running? → return
  │       ├─ Authz: AccessControl.assert_verified(event)
  │       │    └─ FAIL → log + metrics, return
  │       ├─ Idempotency: is_duplicate(service_id, event_id)?
  │       │    └─ YES → log + return
  │       └─ __handle_event(event)
  │             ├─ Tracer: start span "handle.{event_type}"
  │             ├─ correlation_context: set correlation_id
  │             ├─ handle(event)         ← domain logic (subclass)
  │             ├─ Supervisor: record_success(service_id)
  │             ├─ Metrics: timer + increment
  │             └─ On Exception:
  │                  ├─ events_failed += 1
  │                  ├─ Supervisor: record_failure(service_id)
  │                  └─ Metrics: increment events.failed
  │
  ▼
Service may emit downstream events inside handle()
  └─ Event signed with Ed25519 identity
  └─ Authz.assert_publish + trust registered
  └─ bus.publish(signed)
```

---

## 3. Event Type Catalog

Source: `underwrite/events.py` — 80+ event types in the `EventType` enum.

| Domain | Events |
|--------|--------|
| **Core** | `seed.added`, `user.added`, `loan.originated`, `repaid`, `default.occurred`, `revoked` |
| **Quote/Pricing** | `quote`, `quote.calculated`, `pricing.request`, `pricing.computed` |
| **KYC/AML** | `kyc.verified`, `kyc.rejected`, `aml.cleared`, `aml.frozen` |
| **Fraud** | `fraud.alert`, `fraud.wash.flag`, `fraud.velocity.flag` |
| **Risk** | `risk.scored`, `risk.early_warning` |
| **NPA** | `npa.bucket_changed`, `npa.dlg.triggered` |
| **Collateral** | `collateral.marked`, `collateral.liquidated` |
| **Governance** | `governance.proposal`, `governance.executed` |
| **Recovery** | `recovery.started`, `recovery.completed` |
| **Identity** | `identity.register`, `identity.registered`, `identity.rotate`, `identity.rotated` |
| **Notification** | `notification.sent` |
| **Reporting** | `report.generated` |
| **Underwriting** | `underwrite.request`, `underwriter.approved`, `underwriter.rejected` |
| **Document** | `document.generated` |
| **Disbursement** | `disbursement.processed` |
| **Collection** | `collection.updated` |
| **Settlement** | `settlement.completed` |
| **Origination** | `origination.create`, `origination.created`, `origination.submit`, `origination.submitted` |
| **Servicing** | `servicing.started` |
| **Payment** | `payment.receive`, `payment.received`, `payment.schedule`, `payment.due`, `payment.overdue`, `payment.check_overdue` |
| **Fee** | `fee.assess`, `fee.assessed`, `fee.pay` |
| **Statement** | `statement.generate`, `statement.generated` |
| **Communication** | `communication.send`, `communication.sent` |
| **Workflow** | `workflow.start`, `workflow.started`, `workflow.advance`, `workflow.completed` |
| **Decision** | `decision.evaluate`, `decision.made` |
| **Graph** | `graph_path`, `graph_credit_limit`, `graph_users`, `graph_path_result`, `graph_credit_limit_result`, `graph_users_result` |
| **Mechanism** | Command events (`add_seed`, `add_user`, `repay`, `originate`, `default`, `revoke`, `quote`), `mechanism.rejected` |
| **Saga** | `saga.started`, `saga.completed`, `saga.rolled_back`, `saga.compensate` |
| **Idempotency** | `idempotency.duplicate_dropped` |

---

## 4. Service Wiring

Source: `underwrite/handler.py`

The `WIRING` dict maps each event type to the list of services that subscribe to it:

| Event Type | Subscribers |
|---|---|
| `seed.added` | audit, origination |
| `user.added` | audit, fraud, compliance, risk, origination |
| `loan.originated` | audit, fraud, risk, npa, collateral, collection, servicing, payment, fee |
| `repaid` | audit, fraud, collection, payment, servicing |
| `default.occurred` | audit, npa, collateral, recovery, settlement, workflow |
| `revoked` | audit, graph |
| `quote.calculated` | audit, pricing |
| `kyc.verified` | audit, compliance, workflow |
| `kyc.rejected` | audit, compliance, notification, workflow |
| `aml.cleared` | audit, compliance |
| `aml.frozen` | audit, compliance, notification |
| `fraud.alert` / `wash.flag` / `velocity.flag` | audit, notification, decision |
| `risk.scored` | audit, underwriter, decision |
| `risk.early_warning` | audit, notification, servicing |
| `npa.bucket_changed` | audit, notification, collection |
| `dlg.triggered` | audit, notification, recovery |
| `collateral.marked` | audit |
| `collateral.liquidated` | audit, settlement |
| `underwriter.approved` | audit, document, disbursement, workflow |
| `underwriter.rejected` | audit, notification, workflow |
| `pricing.computed` | audit, quote, document |
| `document.generated` | audit, disbursement, communication |
| `disbursement.processed` | audit, servicing |
| `origination.created` | audit, underwriter, workflow |
| `origination.submitted` | audit, risk, fraud, compliance |
| `payment.received` | audit, collection, servicing, statement |
| `payment.due` | audit, notification, communication |
| `payment.overdue` | audit, collection, fee, notification |
| `settlement.completed` | audit, servicing, reporting |
| `decision.made` | audit, underwriter, workflow |
| `workflow.started` | audit |
| `workflow.completed` | audit, notification |
| `recovery.started` | audit, workflow |

Each service also subscribes to its own name as an event type for direct command routing (e.g., `mechanism` subscribes to `"mechanism"` for command events).

---

## 5. Graceful Shutdown

Source: `underwrite/runtime.py:559`, `underwrite/services/base.py:239`, `underwrite/bus.py:575`

```
Runtime.stop()
  │
  ├─1. Metrics export stop event set
  │     └─ metrics thread joined (timeout 5s)
  │
  ├─2. For each service:
  │     ├─ __running = False
  │     ├─ bus.unsubscribe(subscription_id) for all subscriptions
  │     └─ subscriptions list cleared
  │
  ├─3. bus.stop()
  │     ├─ __running = False
  │     ├─ handlers.clear()
  │     ├─ buffer.clear()
  │     ├─ thread pool: wait futures (timeout 5s), shutdown(wait=False)
  │     └─ futures cleared
  │
  └─4. Store shutdown
        ├─ primary store.shutdown()
        └─ read store.shutdown() (if separate)
```

---

## 6. Saga Orchestration Flow

Source: `underwrite/saga.py`

```
start_saga(name, steps) → saga_id
  │
  │  Saga created with:
  │    saga_id (UUID)
  │    steps: [{name, forward_event_type, forward_payload,
  │             compensate_event_type, compensate_payload}, ...]
  │    status: "started"
  │  Persisted to Store
  │
  ▼
execute_all(saga_id)
  │
  │  For i in range(len(steps)):
  │    ├─ execute_step(saga_id, i)
  │    │    ├─ Check idempotency: saga_step:{saga_id}:{i} exists? → skip
  │    │    ├─ Get emitter (NanoService) for saga name
  │    │    ├─ emitter.emit(step.forward_event_type, step.forward_payload)
  │    │    ├─ Record completed_step index
  │    │    ├─ Persist to Store
  │    │    └─ On failure → __rollback(saga_id, failed_step, error)
  │    │
  │    └─ If step fails → return False
  │
  ├─ Happy path: saga.status = "completed", persist
  │
  └─ Rollback path (__rollback):
       ├─ saga.status = "compensating"
       ├─ For each completed step in REVERSE order:
       │    └─ emitter.emit(step.compensate_event_type, step.compensate_payload)
       ├─ saga.status = "rolled_back"
       └─ Persist

Crash recovery: replay_saga(saga_id)
  ├─ Load saga from Store
  ├─ Find next unexecuted step after last completed step
  └─ execute remaining steps (idempotent via store keys)
```

---

## 7. Sequence Diagrams

### 7.1 Runtime Startup Sequence

```mermaid
sequenceDiagram
    participant Caller as CLI / main()
    participant RT as Runtime.__init__
    participant Config as Configuration
    participant Store as Store
    participant Bus as LocalBus
    participant T as Tracer
    participant M as MetricsCollector
    participant A as AccessControl
    participant S as SagaOrchestrator
    participant Sup as ServiceSupervisor
    participant Svcs as NanoService[]

    Caller->>RT: Runtime(config)
    RT->>Config: Configuration.load()
    Config-->>RT: config

    RT->>Store: __build_store()
    Store-->>RT: Sqlite(file_path)|Sqlite(":memory:")

    RT->>Bus: LocalBus(rate_limit, max_workers, store)
    Bus-->>RT: bus

    opt tracing.enabled
        RT->>T: Tracer(service_id, exporter)
        T-->>RT: tracer
    end

    opt metrics.enabled
        RT->>M: MetricsCollector()
        M-->>RT: metrics
    end

    opt authz.enabled
        RT->>A: AccessControl(policy_file)
        A-->>RT: authz
    end

    opt saga.enabled
        RT->>S: SagaOrchestrator(store)
        S-->>RT: saga
    end

    opt recovery.auto_restart
        RT->>Sup: ServiceSupervisor(max_restarts, backoff)
        Sup-->>RT: supervisor
    end

    RT->>RT: __register_subsystem_health()
    RT-->>Caller: Runtime (initialized)

    alt new saga detected
        monitor->>monitor: notify operators
    end
```

### 7.2 Event Lifecycle

```mermaid
sequenceDiagram
    participant Src as Source (CLI/HTTP/Service)
    participant Bus as EventBus
    participant DLQ as DeadLetterQueue
    participant CB as CircuitBreaker
    participant RL as RateLimiter
    participant Sub as NanoService.__dispatch
    participant Authz as AccessControl
    participant Idem as IdempotencyGuard
    participant Tracer as Tracer
    participant Metrics as MetricsCollector
    participant Sup as ServiceSupervisor
    participant Handler as handle()

    Src->>Bus: publish(event)
    Bus->>Bus: buffer.append(event)

    Bus->>CB: allow_request(sid)
    alt circuit open
        CB-->>Bus: denied
        Bus->>DLQ: put(event, "circuit_open", sid)
    else allowed
        CB-->>Bus: allowed
        Bus->>RL: check(sub:sid)
        alt rate limited
            RL-->>Bus: denied
            Bus->>DLQ: put(event, "rate_limited", sid)
        else allowed
            Bus->>Sub: dispatch(event)
            Sub->>Authz: assert_verified(event)
            alt invalid signature
                Authz-->>Sub: AuthzError
                Sub->>Metrics: increment authz.failures
            else valid
                Sub->>Idem: is_duplicate(service_id, event_id)
                alt duplicate
                    Idem-->>Sub: True → return
                else new
                    Sub->>Tracer: start_span("handle.{event_type}")
                    Sub->>Handler: handle(event)
                    Handler->>Handler: domain logic
                    Handler-->>Sub: return
                    Sub->>Sup: record_success(service_id)
                    Sub->>Metrics: timer + increment
                    Tracer-->>Sub: end_span
                end
            end
        end
    end
```

### 7.3 Service Dispatch Pipeline

```mermaid
sequenceDiagram
    participant Bus as LocalBus.__flush
    participant Sub as NanoService.__dispatch
    participant Authz as AccessControl
    participant Idem as IdempotencyGuard
    participant Tracer as Tracer
    participant Sup as ServiceSupervisor
    participant Metrics as MetricsCollector
    participant Handler as NanoService.handle()

    Bus->>Sub: __dispatch(event)
    Note over Sub: Cross-cutting pipeline (ordered)

    alt service not running
        Sub-->>Bus: return (event dropped)
    else running
        Sub->>Authz: assert_verified(event)
        opt AuthzError raised
            Authz-->>Sub: log + metrics(events.authz_failed)
            Sub-->>Bus: return
        end

        Sub->>Idem: is_duplicate(service_id, event_id)
        opt is duplicate
            Idem-->>Sub: True → log + return
        end

        Note over Sub,Tracer: Execution phase
        Sub->>Tracer: span context manager
        Tracer->>Tracer: start_span(trace_id, parent_span_id)

        Sub->>Sub: set correlation_context.correlation_id
        Sub->>Handler: handle(event)
        Handler->>Handler: domain logic
        alt success
            Handler-->>Sub: return
            Sub->>Sup: record_success(service_id)
            Sub->>Metrics: timer("handle.duration")
            Sub->>Metrics: increment("events.handled")
        else exception
            Handler-->>Sub: raise
            Sub->>Sup: record_failure(service_id)
            Sub->>Metrics: increment("events.failed")
        end

        Tracer->>Tracer: end_span
    end
```

### 7.4 Saga Orchestration (Happy Path + Rollback)

```mermaid
sequenceDiagram
    participant Caller as Client
    participant Saga as SagaOrchestrator
    participant Store as Store
    participant Emitter as NanoService
    participant Bus as EventBus

    Note over Caller,Bus: Happy Path
    Caller->>Saga: start_saga("loan_origination", steps)
    Saga->>Store: persist saga (status=started)
    Saga-->>Caller: saga_id

    Caller->>Saga: execute_all(saga_id)

    loop each step i
        Saga->>Store: check idempotency key
        Store-->>Saga: not found
        Saga->>Emitter: emit(forward_event_type, forward_payload)
        Emitter->>Bus: publish(event)
        Saga->>Store: persist completed_step i
    end

    Saga->>Store: persist saga (status=completed)
    Saga-->>Caller: True (success)

    Note over Caller,Bus: Rollback Path (step 2 fails)

    Caller->>Saga: execute_all(saga_id)
    Saga->>Emitter: emit(forward_event_type, step0)
    Saga->>Store: persist step0 complete
    Saga->>Emitter: emit(forward_event_type, step1)
    Saga->>Store: persist step1 complete
    Saga->>Emitter: emit(forward_event_type, step2)
    Emitter-->>Saga: Exception!
    Saga->>Saga: __rollback(saga_id, step2, error)

    rect rgb(255, 200, 200)
        Note over Saga: Compensating in REVERSE order
        Saga->>Emitter: emit(compensate_event_type, step1)
        Saga->>Emitter: emit(compensate_event_type, step0)
    end

    Saga->>Store: persist saga (status=rolled_back, error)
    Saga-->>Caller: False (failure)
```

### 7.5 HTTP API Request Flow

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI as FastAPI (serve.py)
    participant MW as Middlewares
    participant RT as Runtime
    participant Bus as EventBus
    participant Sub as Subscribers

    Client->>FastAPI: POST /v1/publish
    FastAPI->>MW: body_size_middleware
    Note over MW: Rejects >1MB bodies (413)
    MW->>MW: request_id_middleware
    Note over MW: Attaches X-Request-ID header
    MW->>MW: auth_rate_limit_middleware
    Note over MW: Bearer token check (401)<br/>Token-bucket rate limit (429)

    MW->>RT: async_publish(event_type, payload, correlation_id)
    RT->>RT: Event(event_type, source="runtime", payload)
    RT->>Bus: bus.publish(event)
    Bus->>Bus: buffer.append(event), flush()
    Bus-->>RT: event_id
    RT-->>MW: return
    MW-->>FastAPI: 202 Accepted
    FastAPI-->>Client: {"status": "accepted"}

    par dispatch to subscribers
        Bus->>Sub1: dispatch(event)
        Bus->>Sub2: dispatch(event)
        Bus->>SubN: dispatch(event)
    end

    Note over Client,FastAPI: Other endpoints
    Client->>FastAPI: GET /healthz (or /v1/health)
    FastAPI->>RT: runtime.health.status()
    RT-->>FastAPI: status dict
    FastAPI-->>Client: 200 OK / 503

    Client->>FastAPI: GET /v1/metrics
    FastAPI->>RT: metrics_as_text(runtime)
    RT-->>FastAPI: Prometheus text
    FastAPI-->>Client: text/plain; version=0.0.4
```

### 7.6 Graceful Shutdown Sequence

```mermaid
sequenceDiagram
    participant Signal as SIGTERM/SIGINT
    participant RT as Runtime
    participant MThread as Metrics Thread
    participant Svc1 as NanoService (audit)
    participant Svc2 as NanoService (risk)
    participant Bus as LocalBus
    participant Store as Store

    Signal->>RT: stop()

    opt metrics export active
        RT->>MThread: stop_event.set()
        MThread->>MThread: export loop exits
        RT->>MThread: join(timeout=5s)
    end

    par stop all services
        RT->>Svc1: stop()
        Svc1->>Svc1: __running = False
        Svc1->>Bus: unsubscribe(sid) for each subscription
        Bus->>Bus: remove handler from __handlers

        RT->>Svc2: stop()
        Svc2->>Svc2: __running = False
        Svc2->>Bus: unsubscribe(sid) for each subscription
    end

    RT->>Bus: stop()
    Bus->>Bus: __running = False
    Bus->>Bus: __handlers.clear()
    Bus->>Bus: __buffer.clear()

    opt threadpool executor active
        Bus->>Bus: wait futures (timeout 5s)
        Bus->>Bus: shutdown(wait=False)
    end

    RT->>Store: shutdown()
    Store-->>RT: closed

    opt read store exists
        RT->>Store: read_store.shutdown()
    end
```

### 7.7 Loan Origination End-to-End Flow

```mermaid
sequenceDiagram
    participant Client
    participant Bus as EventBus
    participant Mech as MechanismService
    participant Orig as OriginationService
    participant UW as UnderwriterService
    participant Risk as RiskService
    participant Fraud as FraudService
    participant Compl as ComplianceService
    participant Doc as DocumentService
    participant Disb as DisbursementService
    participant Wf as WorkflowService
    participant Audit as AuditService

    Note over Client,Audit: 1. Seed the protocol
    Client->>Bus: emit "mechanism" {command: "add_seed", user: "bank", base_budget: 100000}
    Bus->>Mech: dispatch
    Mech->>Mech: add_seed()
    Mech->>Bus: emit "seed.added" {user: "bank", ...}

    Note over Client,Audit: 2. Add borrower
    Client->>Bus: emit "mechanism" {command: "add_user", sponsor: "bank", user: "alice", delegation_amount: 50000}
    Bus->>Mech: dispatch
    Mech->>Mech: add_user()
    Mech->>Bus: emit "user.added" {sponsor: "bank", user: "alice", ...}

    Note over Client,Audit: 3. Create loan application
    Client->>Bus: emit "origination.create" {borrower: "alice", principal: 10000}
    Bus->>Orig: dispatch
    Orig->>Orig: create application record
    Orig->>Bus: emit "origination.created" {application_id, borrower, principal}

    Bus->>UW: dispatch origination.created
    UW->>Bus: emit "underwrite.request" {borrower: "alice", principal: 10000}

    Bus->>Audit: dispatch origination.created
    Bus->>Wf: dispatch origination.created

    Note over Client,Audit: 4. Submit application
    Client->>Bus: emit "origination.submit" {application_id}
    Bus->>Orig: dispatch
    Orig->>Orig: mark as submitted
    Orig->>Bus: emit "origination.submitted" {application_id, borrower, principal}

    Bus->>Risk: dispatch
    Bus->>Fraud: dispatch
    Bus->>Compl: dispatch
    Bus->>Audit: dispatch

    Note over Client,Audit: 5. Underwriter evaluates
    UW->>UW: evaluate request
    alt approved
        UW->>Bus: emit "underwriter.approved" {borrower, principal}

        Bus->>Doc: dispatch → Doc generates docs
        Bus->>Disb: dispatch → Disb processes
        Bus->>Wf: dispatch → advance workflow
        Bus->>Audit: dispatch

        Doc->>Bus: emit "document.generated" {...}
        Disb->>Bus: emit "disbursement.processed" {...}
        Disb->>Bus: emit "settlement.completed" {...}
    else rejected
        UW->>Bus: emit "underwriter.rejected" {borrower, principal, reasons}
        Bus->>Notification: dispatch
    end

    Note over Client,Audit: 6. (If approved) Execute loan
    Client->>Bus: emit "mechanism" {command: "originate", borrower: "alice", principal: 10000, term: 12, ...}
    Bus->>Mech: dispatch
    Mech->>Mech: originate()
    Mech->>Bus: emit "loan.originated" {borrower, principal, term, ...}

    par downstream subscribers
        Bus->>Audit: dispatch
        Bus->>Fraud: dispatch
        Bus->>Risk: dispatch
        Bus->>NPA: dispatch
        Bus->>Collateral: dispatch
        Bus->>Collection: dispatch
        Bus->>Servicing: dispatch
        Bus->>Payment: dispatch
        Bus->>Fee: dispatch
    end
```

---

## 8. Component Reference

| Component | File | Responsibility |
|---|---|---|
| `Runtime` | `runtime.py` | Lifecycle management, service registration, wiring, start/stop |
| `EventBus` / `LocalBus` | `bus.py` | In-process pub-sub with circuit breaker, rate limiter, DLQ |
| `NanoService` | `services/base.py` | Abstract base: signing, emit, subscribe, dispatch, tracing, idempotency |
| `StatefulService` | `services/base.py` | Base with state lock and store repository helpers |
| `Event` / `EventType` | `events.py` | Event envelope with UUID, timestamp, payload, Ed25519 signature |
| `AccessControl` | `authz.py` | Policy evaluation + Ed25519 signature verification |
| `Tracer` | `tracer.py` | Span lifecycle with Console/Otlp exporters |
| `MetricsCollector` | `metrics.py` | Counters, timers, gauges with tag dimensions |
| `SagaOrchestrator` | `saga.py` | Forward execution + compensating rollback, persisted to store |
| `ServiceSupervisor` | `supervisor.py` | Failure tracking and auto-restart with exponential backoff |
| `SecretsManager` | `secrets.py` | Secret rotation and retrieval |
| `IdempotencyGuard` | `bus.py` | Duplicate event detection by (handler_id, event_id) |
| `CircuitBreaker` | `bus.py` | Per-subscriber circuit breaker (CLOSED → OPEN → HALF_OPEN) |
| `DeadLetterQueue` | `bus.py` | Bounded failed-event storage with optional Store persistence |
| `RateLimiter` | `bus.py` | Token-bucket rate limiter per subscriber key |
| `Store` | `store.py` | SQLite persistence (file path or `:memory:`) |
| `HealthRegistry` | `health.py` | Subsystem health check registration and status aggregation |
| `Configuration` | `config.py` | JSON-driven config with typed subsections |
| `create_app` | `serve.py` | FastAPI app factory with auth, rate-limit, middleware |
| CLI | `cli.py` | Typer CLI for `run`, `serve`, `health`, `dlq`, `metrics`, `migrate` |
| `PayloadValidator` | `validate.py` | Type-safe payload extraction with validation |
| `Identity` | `identity.py` | Ed25519 key pair generation and signing |
| `DelegationGraph` | `services/mechanism/graph.py` | Protocol state machine (seeds, users, loans, edges) |
