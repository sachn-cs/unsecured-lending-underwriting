# Failure handling

Underwrite is designed to **fail loudly, recover automatically, and
leave an audit trail**. This page is the reference for the four
mechanisms that together make the runtime resilient under load,
partial outages, and buggy code.

## The four mechanisms

| Mechanism | Where it lives | What it does |
|-----------|---------------|--------------|
| **DLQ** | `underwrite.dlq.Queue` | Captures every failed event with its original error and the failing subscriber id |
| **Idempotency** | `underwrite.bus.Guard` | Drops duplicate events silently so at-least-once delivery is safe to replay |
| **Circuit breaker** | `underwrite.circuit.Breaker` | Opens after N failures, half-opens after the recovery window, closes on success |
| **Supervisor** | `underwrite.supervisor.Watcher` | Restarts failed services with exponential backoff |

These compose: a misbehaving service fills the DLQ, the breaker
trips, the supervisor restarts the service, and the DLQ is replayed
once the service is healthy again.

## Dead-letter queue

Every handler exception is captured:

```python
try:
    handler(event)
except Exception as exc:
    self.dlq.put(event, error=f"{type(exc).__name__}: {exc}", subscriber_id=sid)
```

The DLQ is:

- **Bounded.** Default 10,000 records; oldest entries are evicted
  when full.
- **Deduplicated.** Poison messages that fail repeatedly update
  the existing record instead of growing the queue.
- **Capped.** The persistent blob is also capped at 16 MiB by
  default; the runtime trims oldest entries when the cap is hit.
- **PII-redacted.** Records are redacted via `redact_event` before
  persistence.
- **Replayable.** `dlq.replay(bus)` re-publishes everything; the
  idempotency guard makes it safe.

```bash
underwrite dlq              # inspect
underwrite dlq --replay     # replay
underwrite dlq --max 10     # replay at most 10
```

## Idempotency

Every `(handler_id, event_id)` pair is cached for the lifetime of
the runtime. The cache is:

- **Bounded.** 1,000 ids per handler × 50 handlers = 50,000
  entries. Oldest entries are evicted when full.
- **Fast.** O(1) lookup per dispatch.
- **Silent on rejection.** Duplicates do not generate log noise;
  they are dropped with a single `debug` line.

Use `runtime.bus.idempotency.is_duplicate(handler_id, event_id)`
when you need to know whether a particular event has been seen.

## Circuit breaker

Every subscriber has a circuit breaker. The breaker has three
states:

```
                  ┌─────────────────┐
                  │     CLOSED      │
                  │ (passing)       │
                  └────────┬────────┘
                           │
              N failures   │
                           ▼
                  ┌─────────────────┐
                  │      OPEN       │
                  │ (failing)       │
                  └────────┬────────┘
                           │
            recovery_window │
                           ▼
                  ┌─────────────────┐
                  │   HALF_OPEN     │
                  │ (probe)         │
                  └────────┬────────┘
                           │
             next event    │
                           ▼
                  success → CLOSED
                  failure → OPEN
```

The breaker is **transparent** to handlers. You only see the
symptoms (DLQ growing, no `handle` calls).

Default thresholds:

- **3 failures** within the recovery window trips the breaker.
- **15 seconds** is the recovery window before half-opening.
- One success in `HALF_OPEN` closes the breaker.

## Supervisor

The supervisor watches every running service. When a service
crashes, the supervisor restarts it with exponential backoff:

- **3 maximum restarts** before the service is marked unhealthy.
- **1 second base backoff**, doubling per attempt, with jitter.

The supervisor's health is exposed via `runtime.health.status()`:

```python
runtime.health.status()
# {"bus": {...}, "store": {...}, "authz": {...}, "metrics": {...},
#  "tracer": {...}, "saga": {...}, "supervisor": {"restarts": 1, "backoff_ms": 2000}}
```

## Sagas and compensating actions

Multi-step workflows use the saga orchestrator. Each step has:

- A **forward action** (the business logic).
- An optional **compensating action** (rollback).

If any step fails, the orchestrator runs the compensating actions
in reverse order. The saga emits `saga.rolled_back` with the failed
step.

```python
from underwrite.saga import Orchestrator, Step

orchestrator = Orchestrator(store=runtime.store)

async def create_loan(event):
    # ...
    return {"loan_id": "L100"}

async def compensate_loan(loan_id):
    # undo the loan creation
    ...

saga = orchestrator.start(
    "loan_creation",
    [
        Step(name="kyc", forward=kyc_step, compensate=kyc_rollback),
        Step(name="pricing", forward=pricing_step, compensate=pricing_rollback),
        Step(name="originate", forward=create_loan, compensate=compensate_loan),
    ],
)
```

The orchestrator's persistence is in-memory by default; saga state
spans restarts via the store in a future release (see ROADMAP).

## Composing the mechanisms

A typical failure path:

1. Service A publishes `loan.originated`.
2. Service B's handler raises `ConnectionError` to the bureau API.
3. The bus catches the exception and calls `dlq.put`.
4. The breaker for B records a failure. After 3 failures, the
   breaker opens.
5. Subsequent events for B are routed straight to the DLQ with a
   `breaker_open` note.
6. After 15 seconds, the breaker half-opens. The next event is
   allowed through.
7. If the bureau API recovers, the handler succeeds; the breaker
   closes.
8. If the bureau API is still down, the handler fails; the breaker
   reopens for another 15 seconds.
9. Meanwhile, the supervisor has restarted B's underlying process
   if it crashed.
10. Operators inspect `underwrite dlq` and decide whether to replay
    the buffered events.

## What you should not do

- **Don't catch broad exceptions in handlers.** Catch what you can
  handle; let everything else propagate to the bus, which will
  DLQ and break.
- **Don't disable idempotency in services.** It is a runtime
  invariant, not a per-service opt-in.
- **Don't replay the DLQ without fixing the underlying failure.**
  The DLQ is durable and will keep the events; replaying into a
  still-broken service just moves them around.
- **Don't bypass the breaker.** The breaker is what protects the
  rest of the runtime from a cascading failure.

## See also

- [Architecture](architecture.md) — where the mechanisms fit in the layered design.
- [Observability](../operate/observability.md) — alerting on DLQ growth and breaker state.
- [DLQ and replay](../operate/dlq.md) — operational playbook for DLQ inspection.