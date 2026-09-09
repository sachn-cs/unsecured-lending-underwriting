# Services

The 34 wired nano-services and how to wire a custom service into
the runtime. Each service is a small `Core` subclass that subscribes
to event types and emits its own.

## The 34 wired services

| Service | Purpose | Subscribed events |
|---------|---------|-------------------|
| `mechanism` | Delegation state machine (the heart of the platform) | command events |
| `audit` | PII-redacted event ledger | every event type (mirror) |
| `risk` | ML risk scoring | loan.application.received |
| `fraud` | Fraud detection | loan.application.received, loan.originated |
| `compliance` | KYC / AML | kyc.check commands |
| `pricing` | RBI-aligned pricing | pricing.compute commands |
| `kfs` | Key Fact Statement | kfs.generate commands |
| `consent` | DPDPA consent lifecycle | consent.record / consent.withdraw |
| `dsr` | Data Subject Rights | dsr.request |
| `credit_bureau` | CIBIL / Experian / Equifax + CKYC | credit_bureau.check |
| `razorpay` | Payment gateway | payment.create, refund.create |
| `underwriter` | Rule engine + risk model | underwriter.evaluate |
| `decision` | Final decision | decision.request |
| `npa` | SMA / NPA / DLG classification | loan events |
| `collateral` | Collateral mark / liquidate | loan events |
| `recovery` | Default recovery | default.occurred |
| `governance` | Governance proposals | proposal commands |
| `notification` | Multi-channel notifications | fraud.alert, npa.* events |
| `reporting` | Report generation | reporting commands |
| `document` | Document generation | document commands |
| `disbursement` | Disbursement processing | approval events |
| `collection` | Collection updates | repayment events |
| `settlement` | Settlement completion | settlement events |
| `origination` | Origination creation | application events |
| `servicing` | Loan servicing | loan events |
| `payment` | Payment handling | payment events |
| `communication` | Communication dispatch | notification events |
| `workflow` | Workflow management | workflow commands |
| `fee` | Fee assessment | loan events |
| `statement` | Statement generation | statement commands |
| `prepayment` | Prepayment processing | prepayment commands |
| `graph` | Delegation graph operations | graph commands |
| `identity` | Identity management | identity commands |

Plus four KYC provider clients: `pan`, `aadhaar`, `cibil`, `ckyc`.
The full count is 34 wired services plus 4 providers.

## The `Core` base class

Every service extends `Core`:

```python
class MyService(Core):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscribe("loan.originated")

    def handle(self, event: Message) -> None:
        # domain logic — called by dispatch
        ...
        self.emit("downstream.event", result_payload)
```

The base class wires:

- `authz.assert_verified(event)` before invoking the handler
- `bus.idempotency.is_duplicate(...)` before invoking the handler
- `tracer.start_span(...)` around the handler
- `metrics.increment(...)` after the handler succeeds
- `metrics.timer(...)` for handler latency
- `supervisor.record_success(...)` after the handler succeeds
- `bus.dlq.put(...)` on handler exception
- `circuit_breaker.record_failure(...)` on handler exception

You write the domain logic; the base class wires the guarantees.

## The `Emitter` helper

`self.emit(event_type, payload)` creates a `Message`, signs it with
the service's Ed25519 key, and publishes it on the bus. You do not
see any of this — the base class abstracts it away.

```python
class PricingService(Core):
    def handle(self, event):
        # ... compute pricing ...
        self.emit("pricing.computed", {
            "loan_id": event.payload["loan_id"],
            "apr": 0.289,
            "emi": 16543.20,
            # ...
        })
```

## The `StatefulService` base class

For services that need durable state:

```python
from underwrite.services.base import StatefulService


class AuditService(StatefulService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscribe("every.event.type")

    def handle(self, event):
        sanitized = redact_event(event)
        self.set(f"audit:{event.event_id}", sanitized.to_dict())
```

`StatefulService` adds `set`, `get`, and `delete` methods backed by
the configured store. The base class also acquires a per-instance
lock around the handler so concurrent events on the same key are
serialised.

## The `Dependencies` bundle

For services with many collaborators, use `Dependencies`:

```python
from underwrite.services.base import Dependencies

deps = Dependencies(
    identity=keypair,
    bus=runtime.bus,
    store=runtime.store,
    metrics=runtime.metrics,
    health=runtime.health,
    authz=runtime.authz,
    tracer=runtime.tracer,
    saga=runtime.saga,
    supervisor=runtime.supervisor,
    secrets_manager=runtime.secrets,
    max_concurrent=4,
)

service = MyService.from_dependencies(name="my_service", deps=deps)
```

## Subscriptions and routing

A service declares its interests in `__init__`:

```python
self.subscribe("loan.originated")
self.subscribe("loan.repaid")
self.subscribe("loan.defaulted")
```

The base class registers each subscription with the bus. The
runtime fires events on the bus; the bus dispatches them to every
subscriber; the base class handles authz and idempotency before
the handler runs.

## Service lifecycle

```python
class MyService(Core):
    def start(self):
        # called by the runtime when the service is started
        self.running = True

    def stop(self):
        # called by the runtime on shutdown
        self.executor.shutdown(wait=True)
        for sid in self.subscriptions:
            self.bus.unsubscribe(sid)
```

`Core.stop` is the default and handles executor shutdown and
subscription cleanup. Override `start` if your service needs to do
initialization that requires the runtime to be wired (e.g.,
opening a network connection).

## Wiring a custom service

To wire a custom service:

1. **Define the service** — subclass `Core` (or `StatefulService`).
2. **Declare subscriptions** — call `self.subscribe(event_type)`
   in `__init__`.
3. **Implement `handle`** — receive a `Message`, do your domain
   logic, optionally call `self.emit`.
4. **Register with the runtime** — call `runtime.register(name,
   instance)` or `runtime.register(name)` to instantiate by name.
5. **Start the runtime** — `runtime.start([name, ...])`.

The runtime will:

- Trust the service identity with authz.
- Register the subscriptions with the bus.
- Attach the metrics, tracer, and supervisor.
- Inject the bus, store, and other dependencies.

## What you should not do

- **Don't import other services.** Services compose through the
  bus, not through direct calls. If you find yourself importing
  another service, refactor to publish an event instead.
- **Don't write the dispatch logic yourself.** The base class
  handles it; writing your own bypasses authz, idempotency, and
  tracing.
- **Don't catch broad exceptions in handlers.** Catch what you can
  handle; let everything else propagate to the DLQ.
- **Don't disable the audit service.** Every event should be
  audited.

## See also

- [Architecture](../understand/architecture.md) — where services fit in the layered design.
- [Configuration](configuration.md) — the per-service config block.
- [Events](../understand/events.md) — the event envelope services send and receive.