# Tutorial: custom nano-services

You have built a single `Greeter` service and seen how the event bus
wires authz, idempotency, tracing, metrics, and the DLQ. Now you will
see how to compose multiple services into a coherent domain — the
patterns the 34 wired services use, distilled.

## What you will build

A two-service flow for a small invoicing domain:

1. `InvoiceService` listens for `invoice.created` and emits
   `invoice.totals_computed` with the line totals.
2. `LedgerService` listens for `invoice.totals_computed` and records
   the invoice in the ledger.

You will see how the two services communicate **only through events**
and how to test them in isolation.

## The pattern: stateless reducers

The 34 wired services are mostly **stateless reducers**: a function
from `(event, store)` to `(emit_or_none, store_delta)`. Underwrite
gives them a `Core` wrapper that injects the bus, store, authz,
tracing, metrics, idempotency, and DLQ.

```python
class InvoiceService(Core):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.subscribe("invoice.created")

    def handle(self, event: Message) -> None:
        line_items = event.payload["line_items"]
        subtotal = sum(item["qty"] * item["price"] for item in line_items)
        tax = subtotal * 0.18
        total = subtotal + tax

        self.emit(
            "invoice.totals_computed",
            {
                "invoice_id": event.payload["invoice_id"],
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
            },
        )
```

Three properties of this style:

- **No cross-service imports.** `InvoiceService` does not know
  `LedgerService` exists. The wiring happens in `handler.py` via the
  `WIRING` table.
- **No shared in-memory state.** Every piece of cross-service state
  goes through the bus. State that survives across runs goes through
  the `Store`.
- **One `handle()` per service.** A service does **one** thing. If
  you find yourself branching on event type, split the service.

## The pattern: stateful reducers

For services that need durable state — like `LedgerService` — use
`StatefulService` (a subclass of `Core`):

```python
from underwrite.services.base import StatefulService


class LedgerService(StatefulService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.subscribe("invoice.totals_computed")

    def handle(self, event: Message) -> None:
        invoice_id = event.payload["invoice_id"]
        self.set(f"ledger:{invoice_id}", event.payload)
        self.emit("invoice.recorded", {"invoice_id": invoice_id})
```

`self.set(key, value)` writes through the configured store; `self.get`
and `self.delete` round-trip the same way. The base class also
acquires a per-instance lock around the handler so two concurrent
events on the same key are serialised.

## The pattern: cross-cutting middleware

Some concerns are best implemented as middleware around the dispatch
loop rather than as services. The `LocalBus.dispatch` already does
this for authz, idempotency, and the circuit breaker. Add your own
by subclassing `LocalBus`:

```python
from underwrite.local import LocalBus


class AuditedBus(LocalBus):
    def dispatch(self, handler, event, sid):
        loguru.logger.info("dispatch {} -> {}", sid, event.event_type)
        super().dispatch(handler, event, sid)
```

Or, more idiomatically, write a thin middleware that wraps the
handler:

```python
def with_timing(handler, label):
    def wrapped(event):
        start = time.monotonic()
        try:
            handler(event)
        finally:
            elapsed = (time.monotonic() - start) * 1000
            loguru.logger.info("{} took {:.2f} ms", label, elapsed)
    return wrapped
```

## Testing patterns

### Pattern 1 — unit-test the handler in isolation

```python
def test_invoice_service_totals():
    bus = MagicMock()
    store = MagicMock()
    svc = InvoiceService(name="invoice", bus=bus, store=store)

    event = Message.signed(
        keypair, type="invoice.created", source="test",
        payload={"invoice_id": "INV-1", "line_items": [
            {"qty": 2, "price": 50.0},
            {"qty": 1, "price": 100.0},
        ]},
    )
    svc.handle(event)

    bus.emit.assert_called_once()
    args = bus.emit.call_args[0]
    assert args[0] == "invoice.totals_computed"
    assert args[1]["subtotal"] == 200.0
    assert args[1]["tax"] == 36.0
    assert args[1]["total"] == 236.0
```

### Pattern 2 — integration-test through a real Runtime

```python
def test_two_services_integration():
    captured = []

    with Runtime() as runtime:
        InvoiceService(name="invoice", bus=runtime.bus, store=runtime.store)
        LedgerService(name="ledger", bus=runtime.bus, store=runtime.store)
        runtime.register("invoice")
        runtime.register("ledger")
        runtime.start(["audit"])

        runtime.bus.subscribe("invoice.recorded", lambda m: captured.append(m))

        runtime.publish("invoice.created", {
            "invoice_id": "INV-1",
            "line_items": [{"qty": 1, "price": 100.0}],
        })

    assert len(captured) == 1
    assert captured[0].payload == {"invoice_id": "INV-1"}
```

### Pattern 3 — property-based test with Hypothesis

For reducers that are pure functions of `(event, store)`, generate
random events and assert invariants:

```python
from hypothesis import given, strategies as st


@given(st.lists(st.floats(min_value=0, max_value=10_000), min_size=1, max_size=20))
def test_invoice_totals_are_non_negative(line_totals):
    items = [{"qty": 1, "price": t} for t in line_totals]
    # ... construct event, call handle, assert subtotal >= 0, total >= subtotal ...
```

The existing test suite uses Hypothesis in `test_property_validators.py`
and a handful of others.

## Wiring the services together

The runtime wires subscribers automatically. The `WIRING` table in
`underwrite/handler.py` is a static mapping from event type to
handler. For dynamic services — services that are not in the table —
you wire them at registration time:

```python
runtime.register("invoice", invoice_svc)  # subscribes to invoice.created
runtime.register("ledger", ledger_svc)    # subscribes to invoice.totals_computed
```

The base class reads the `__init__` subscriptions and registers them
with the bus. You never call `bus.subscribe` directly from a service.

## When to write a new service

Write a new nano-service when you have **one** of:

- a domain boundary that emits and consumes different event types,
- a new state-bearing entity that the existing services do not own,
- a new integration (KYC provider, payment gateway, notification
  channel) that emits and consumes its own event family.

Do **not** write a new service when:

- you can express the behaviour in a single `handle()` of an existing
  service,
- the new code is a one-off transformation that only one event
  needs,
- the new code is operational (telemetry, authz) — fold it into the
  bus middleware instead.

## Where to go next

- [Tutorial: the event bus](TUTORIAL_EVENT_BUS.md) — what happens
  between publish and handle.
- [Tutorial: pluggable backends](TUTORIAL_PLUGINS.md) — swap the
  store, bus, or tracer.
- [Architecture](architecture.md) — diagrams and design decisions.
- [Services reference](SERVICES.md) — the 34 wired services, with
  the events they emit and consume.