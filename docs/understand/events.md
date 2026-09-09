# Events

Events are the only way services communicate. A `Message` carries
identity, content, and a cryptographic signature; the bus dispatches
it to every subscribed service; the audit service persists it.

This page is the reference for the event envelope, the event
lifecycle, and the 132 typed event kinds.

## The `Message` envelope

```python
@dataclass(frozen=True, slots=True)
class Message:
    event_id: str          # UUID v4
    event_type: str        # from the Type enum
    source: str            # emitting service id
    source_key: str        # Ed25519 public key (base64)
    timestamp: str         # ISO 8601 UTC
    payload: dict          # JSON-native values
    correlation_id: str    # trace continuity
    signature: str         # Ed25519 over canonical bytes
    trace_id: str          # OpenTelemetry trace id
    parent_span_id: str    # OpenTelemetry parent span id
```

`Message` is immutable. Mutations go through `dataclasses.replace`
or, more commonly, by constructing a new `Message` and signing it
via `Message.signed(...)`.

## Canonical signing bytes

```
event_id | timestamp | event_type | source | <sorted-key JSON payload>
```

The signature is over this byte sequence. Two services producing
the same content produce the same signature; an attacker who knows
one trusted key cannot re-stamp events under another service id
without invalidating the signature.

`Message.canonical_sign_bytes()` returns these bytes; the runtime
computes the signature at publish and re-derives the bytes at
verification.

## The 132 typed event kinds

Every event type is a member of the `Message.Type` enum:

```python
class Type(str, enum.Enum):
    SEED_ADDED = "seed.added"
    USER_ADDED = "user.added"
    LOAN_ORIGINATED = "loan.originated"
    # ... 129 more
```

The convention is `<domain>.<action>[.<outcome]>`>`. Use
`Type.SEED_ADDED.value` to get the bare string for serialization
or comparison.

### Domains covered

| Domain | Event kinds |
|--------|-------------|
| Mechanism | seed.added, user.added, loan.originated, loan.drawn, loan.repaid, loan.defaulted |
| Compliance | kyc.verified, kyc.rejected, aml.cleared, aml.frozen, aml.flagged |
| Risk | risk.scored, risk.early_warning |
| Fraud | fraud.alert, fraud.wash.flag, fraud.velocity_flag |
| Credit | credit_bureau.checked, credit_bureau.check_failed |
| Pricing | pricing.computed, pricing.penal_interest, pricing.foreclosure |
| KFS | kfs.generated |
| Consent | consent.recorded, consent.withdrawn, consent.expired |
| DSR | dsr.requested, dsr.fulfilled, dsr.rejected |
| Razorpay | razorpay.mandate.active, razorpay.payment.captured, razorpay.refund.processed |
| Notification | notification.sent |
| Reporting | report.generated |
| Document | document.generated |
| Disbursement | disbursement.processed |
| Collection | collection.updated |
| Settlement | settlement.completed |
| Origination | origination.created, origination.submitted |
| Servicing | servicing.started |
| Payment | payment.received, payment.due, payment.overdue |
| Fee | fee.assessed, penal_interest.assessed |
| Prepayment | prepayment.requested, prepayment.processed, foreclosure.computed |
| Statement | statement.generated |
| Communication | communication.sent |
| Workflow | workflow.started, workflow.completed |
| Decision | decision.made |
| Identity | identity.registered, identity.rotated |
| Notification | (covered above) |
| Audit | audit.appended (internal) |
| Underwriter | underwriter.approved, underwriter.rejected, underwriter.conditional_approved |
| NPA | npa.bucket.changed, npa.dlg.triggered, sma.classified |
| Saga | saga.started, saga.completed, saga.rolled_back |
| Idempotency | idempotency.duplicate_dropped |
| CKYC | ckyc.verify, ckyc.verified, ckyc.rejected |
| Mechanism | mechanism.rejected |
| Recovery | recovery.started, recovery.completed |
| Governance | governance.proposal, governance.executed |

The exact count grows as new services land. The current 132 is the
snapshot at v0.9.

## Event lifecycle

```
                publish                 subscribe
   ┌────────────────────────────────────────────────────────────┐
   │                                                            │
   ▼                                                            │
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  emit   │─▶│  bus    │─▶│ dispatch│─▶│ authz   │─▶│ handler │   │
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘   │
                 │            │            │             │        │
                 ▼            ▼            ▼             ▼        │
            signature    idempotency   signature    metrics       │
            verify       check         verify       record        │
                                                                       │
                                                                       ▼
                                                              DLQ on failure
```

### Step-by-step

1. **emit** — The service calls `self.emit(event_type, payload)`.
   The base class constructs a `Message`, signs it with the
   service's Ed25519 key, and dispatches it on the bus.

2. **bus** — The bus buffers the event (bounded), then flushes to
   subscribers. The buffer's max size is configurable; an overflow
   drops the oldest event and logs a warning.

3. **dispatch** — `LocalBus.dispatch` finds every subscriber for
   the event type and calls `dispatch(handler, event, sid)` for
   each.

4. **authz** — Before invoking the handler, `Core.dispatch` calls
   `AccessControl.verify_signature(event)`. If the signature is
   missing, the source is untrusted, or the timestamp is outside
   the replay window, the event is dropped and the DLQ records
   the failure.

5. **handler** — The handler runs. On success, the supervisor
   records the success and metrics count the event. On exception,
   the DLQ records the event with the original error and the
   circuit breaker increments the subscriber's failure count.

## Constructing events

### Programmatic (services)

```python
from underwrite.services.base import Core
from underwrite.message import Message

class Greeter(Core):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscribe("user.greeted")

    def handle(self, event: Message) -> None:
        name = event.payload["name"]
        self.emit("user.greeted_back", {"name": name, "hello": True})
```

`self.emit` signs with the service identity. Use this in any
service subclass.

### Ad-hoc (drivers and tests)

```python
from underwrite.runtime import Runtime

with Runtime() as runtime:
    runtime.publish("mechanism", {"command": "add_seed", "user": "hdfc"})
```

`runtime.publish` signs with the runtime identity. Use this in
drivers, scripts, and tests.

### With an explicit source

```python
runtime.publish_as(
    source="compliance",
    event_type="kyc.verified",
    payload={"pan": "ABCDE1234F"},
)
```

Use `publish_as` to publish as a specific source identity — useful
for replaying historical events from a service-specific key.

## Subscriptions

```python
class MyService(Core):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscribe("loan.originated")
```

Multiple subscriptions are allowed:

```python
self.subscribe("loan.originated")
self.subscribe("loan.repaid")
self.subscribe("loan.defaulted")
```

The base class registers each subscription with the bus and returns
a subscription id. The id is stored on `self.subscriptions` for
cleanup on `stop()`.

## Idempotency

Every `(handler_id, event_id)` pair is cached. Duplicates are
dropped silently after the first delivery. The cache is bounded
(1,000 ids per handler, 50 handlers) and evicts least-recently-used
when full.

```python
runtime.bus.idempotency.is_duplicate(handler_id, event_id)
# True if this is a re-delivery
```

## Replay

The DLQ stores failed events with their original errors. To replay
the DLQ back onto the bus:

```python
runtime.bus.dlq.replay(runtime.bus)
```

Or from the CLI:

```bash
underwrite dlq --replay
```

Replay is **at-least-once**. Idempotency at the handler ensures
that re-delivery does not double-process the event.

## See also

- [Security](security.md) — signatures, replay windows, PII redaction.
- [Architecture](architecture.md) — how events flow between layers.
- [Failure handling](failure-handling.md) — what happens when an event fails.