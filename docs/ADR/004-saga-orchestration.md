# ADR 004: Saga Orchestration for Distributed Transactions

**Status**: Accepted

## Context

Loan origination in `underwrite` spans multiple nano-services: risk scoring, fraud detection, KYC/AML compliance, document generation, and disbursement. A failure in step 3 (e.g., KYC rejected) must roll back steps 1 and 2 (risk score recorded, fraud alert logged). Each service is stateless with respect to the transaction — they respond to events and persist their own state through a `Store` (`store.py`).

The saga implementation lives in `saga.py`. The `SagaOrchestrator` class (`saga.py:129`) coordinates execution. The `SagaStep` dataclass (`saga.py:38`) defines forward and compensating actions. The `Emitter` Protocol (`saga.py:28`) bridges saga orchestration to `NanoService.emit()`.

## Problem

How should multi-service transactions be coordinated with rollback capability, given that there is no distributed transaction coordinator, no two-phase commit, and services use different `Store` backends (MemoryStore, FileStore, PostgresStore)?

## Decision

Implement a **centralized saga orchestrator** (`SagaOrchestrator`) that:

1. **Executes steps sequentially** — each step emits a forward event via `Emitter.emit()`
2. **Compensates in reverse order** on failure — emits compensating events for each completed step, in reverse order (`saga.py:303`)
3. **Persists state to `Store` after every mutation** — saga status, completed step indices, and error details are written to the store (`saga.py:165-171`)
4. **Uses store-backed idempotency keys** — `saga_step:{saga_id}:{step_index}` is written to the store when a step completes. On replay, completed steps are skipped (`saga.py:226-230`)
5. **Supports crash recovery** — `replay_saga(saga_id)` loads an incomplete saga, finds the next unexecuted step, and resumes execution (`saga.py:334-382`)
6. **Uses per-saga locks** (`saga.py:144-148`) so different sagas execute concurrently

### Saga Definition

```python
SagaStep(
    name="disburse_funds",
    forward_event_type="disbursement.processed",
    forward_payload={"loan_id": "123", "amount": 10000},
    compensate_event_type="disbursement.reversed",
    compensate_payload={"loan_id": "123"},
)
```

### Execution Flow

```
start_saga("loan_origination", steps=[...]) → saga_id (UUID)
execute_all(saga_id):
  for step in steps:
    execute_step(saga_id, step_index):
      - check idempotency key in store (skip if exists)
      - emitter.emit(forward_event_type, forward_payload)
      - record completed step index → persist to store
      - on Exception → __rollback(saga_id, failed_step, error)
  if all succeeded: status = "completed", persist
  on rollback:
    for completed step in REVERSE order:
      emitter.emit(compensate_event_type, compensate_payload)
    saga.status = "rolled_back", persist
```

### Wiring

The saga emitter is registered via `SagaOrchestrator.register_emitter(saga_name, emitter)` (`saga.py:180`). `NanoService.__init__` automatically registers itself with the saga orchestrator if one is provided (`services/base.py:151-152`).

## Alternatives Considered

- **Distributed transactions (XA / two-phase commit)**: Adds a transaction coordinator, database lock contention, and is impractical across different `Store` backends (FileStore and PostgresStore have no common coordination protocol). Two-phase commit also holds locks for the transaction duration, which conflicts with the `NanoService` pattern of emitting events and letting subscribers process asynchronously.

- **Outbox pattern with CDC**: Appropriate for cross-service transactions with Kafka, but adds infrastructure complexity (Kafka cluster, Debezium, schema registry) not justified in a single-process system. The `LocalBus` already provides reliable in-process delivery with DLQ guarantees.

- **Choreographed sagas (each service manages its own compensation)**: Each service would need to know which saga it belongs to and emit its own compensating events on failure. This makes the transaction boundary implicit and harder to reason about, debug, and test. The centralized orchestrator provides a single execution trace (`saga.py:262-285`) that can be logged and inspected.

## Consequences

### Positive
- Crash recovery — incomplete sagas survive process restarts via `replay_saga()` and store-backed idempotency keys
- Compensating events are explicit — each `SagaStep` defines both forward and rollback event types and payloads. The full transaction plan is knowable at definition time
- Per-step idempotency — safe to retry after failure at any step. The idempotency key (`saga_step:{saga_id}:{step_index}`) ensures exactly-once execution semantics for each step
- Concurrent saga execution — per-saga locks allow different sagas to progress independently

### Negative
- Eventual consistency — there is a window between step execution and completion persistence where the system is partially committed. A crash during `execute_step()` but before `persist_saga()` could result in a partially-executed step that `replay_saga()` must handle via idempotency
- No ACID guarantees — sagas provide "compensating transaction" semantics, not atomicity. Compensations themselves can fail (handled by `__rollback()` at `saga.py:309-310`, which logs compensation errors but does not retry them)
- Compensation logic must be implemented per service — adding a saga step requires both forward handling and backward compensation in the target service. Skipping compensation is a `return` which silently no-ops — tracked in `docs/REFACTORING_PLAN.md`.
- Currently in-memory only — `SagaOrchestrator.__init__()` defaults to `MemoryStore` (`saga.py:141`), meaning all sagas are lost on restart unless a durable `Store` (FileStore or PostgresStore) is provided. The `__load_sagas()` method exists but is only effective with persistent store backends
