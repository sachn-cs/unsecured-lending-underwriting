# Sagas

A saga is a multi-step workflow with compensating rollback. Use a
saga when a domain operation spans multiple events and services
and you need atomicity across them.

This page is the reference for `underwrite.saga.Orchestrator` and
the patterns the 34 wired services use to coordinate work.

## When to use a saga

Use a saga when:

- A domain operation spans more than one service.
- Each step has its own forward action and a corresponding
  compensating action.
- The workflow can fail mid-flight, and you need to undo
  successfully completed steps.

Do **not** use a saga when:

- The operation is a single event handled by one service.
- There is no notion of partial completion to roll back from.
- A simpler retry / circuit breaker pattern will suffice.

## The `Step` and `Orchestrator`

```python
from underwrite.saga import Orchestrator, Step

orchestrator = Orchestrator(store=runtime.store)

async def create_user(event):
    # ... domain logic ...
    return {"user_id": "U100"}

async def compensate_user(user_id):
    # undo user creation
    ...

saga = orchestrator.start(
    "user_creation",
    [
        Step(name="kyc", forward=kyc_step, compensate=kyc_rollback),
        Step(name="consent", forward=consent_step, compensate=consent_rollback),
        Step(name="user", forward=create_user, compensate=compensate_user),
    ],
)
```

The orchestrator runs each step in order; on success, it commits
the saga. On failure, it runs the compensating actions in reverse
order.

## Compensation order

Compensating actions run in **reverse order** of the steps that
succeeded. If steps `kyc` and `consent` succeeded but `user` failed,
the orchestrator runs:

1. `compensate_user(...)` — never runs (the step failed)
2. `compensate_consent(...)`
3. `compensate_kyc(...)`

The order matters: each compensating action may depend on the
state set by earlier compensating actions.

## Failure semantics

A step can fail in two ways:

- **Raise an exception.** The orchestrator catches the exception,
  runs compensations, emits `saga.rolled_back`, and stops.
- **Return a failure value.** The step returns a value that the
  orchestrator interprets as a failure; same outcome.

Both paths emit `saga.rolled_back` with the failed step name.

## Idempotency

Each step is idempotent: it can be safely retried. The orchestrator
passes the same `saga_id` and `step_name` to every retry of a
step. Steps should use these to dedupe their work.

The orchestrator itself does not retry by default. Wrap the saga
in your own retry policy if you need at-least-once execution.

## Persistence

Sagas are in-memory by default. State lives in the orchestrator's
internal dict; restart the process and the saga is gone. v1.0 will
persist sagas through the store (see ROADMAP).

For now, use the `replay` method to re-attach to a saga by id after
a process restart. The orchestrator looks up the saga by id and
returns it if it exists in memory.

## Emitting from inside a step

A step is just a Python function. To emit events from inside a
step, accept the `runtime` as a parameter:

```python
async def originate_step(runtime, event):
    runtime.publish("mechanism", {
        "command": "originate",
        "user": event.payload["user"],
        "principal": event.payload["principal"],
    })
    return {"loan_id": "L100"}

async def compensate_originate(loan_id):
    # undo origination
    ...
```

The orchestrator does not pass a runtime directly; you capture it
via closure or pass it through the step's arguments.

## Composition

A saga can emit events that trigger other sagas. There is no global
coordinator; sagas are independent workflows that communicate
through the bus.

```python
saga = orchestrator.start(
    "loan_origination",
    [
        Step(name="kyc", forward=kyc_step, compensate=kyc_rollback),
        Step(name="pricing", forward=pricing_step, compensate=pricing_rollback),
        Step(
            name="originate",
            forward=originate_step,    # publishes "loan.originated"
            compensate=compensate_originate,
        ),
    ],
)
# A separate saga could subscribe to "loan.originated" and run
# post-origination workflows.
```

## What you should not do

- **Don't use a saga for single-step operations.** A saga with one
  step is a wrapper around a regular event handler.
- **Don't call `self.emit` from inside a saga step.** The step runs
  outside the service context; use `runtime.publish` instead.
- **Don't assume compensation always succeeds.** A compensating
  action that fails must be handled (logged, retried, or sent to
  the DLQ for manual intervention).

## See also

- [Architecture](../understand/architecture.md) — where sagas fit in the layered design.
- [Failure handling](../understand/failure-handling.md) — sagas as one of the four failure mechanisms.
- [Events](../understand/events.md) — the events sagas emit and consume.