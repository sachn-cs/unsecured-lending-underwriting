# Tutorial: build your first service

This tutorial walks through writing a `Greeter` nano-service from
scratch. In under fifty lines you will have a service that listens for
`user.greeted` events and emits a `user.greeted_back` event with a
personalized message.

You should be comfortable with Python and the basics of event-driven
systems, but you do **not** need any prior Underwrite experience —
that is what this page is for.

## What you will build

A nano-service that:

1. Subscribes to the `user.greeted` event type.
2. Reads the `name` field from the payload.
3. Emits a `user.greeted_back` event with `hello, <name>!`.
4. Logs the greeting at INFO level.

You will run it inside the `Runtime` and verify the second event
appears in the audit log.

## Step 1 — set up the workspace

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate
mkdir -p greeter
```

The `greeter/` directory will hold the service code. Underwrite does
not require services to live inside the package — you can drop them
anywhere on `sys.path`.

## Step 2 — write the service

Create `greeter/__init__.py` (empty) and `greeter/service.py`:

```python
"""Greeter nano-service: a 50-line hello-world service."""

from __future__ import annotations

import loguru

from underwrite.message import Message
from underwrite.services.base import Core


class Greeter(Core):
    """Responds to ``user.greeted`` with a personalised greeting."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Subscribe via the base class so the runtime wires the handler.
        self.subscribe("user.greeted")

    def handle(self, event: Message) -> None:
        """React to ``user.greeted``."""
        name = event.payload.get("name", "anonymous")
        loguru.logger.info("Greeter handling user.greeted for {}", name)
        self.emit(
            "user.greeted_back",
            {"name": name, "message": f"hello, {name}!"},
        )
```

Three things to notice:

- `self.subscribe("user.greeted")` declares interest in the event type.
  The base class registers the handler with the bus at startup.
- `self.emit(...)` signs the outgoing event with the service's
  Ed25519 key and publishes it on the bus. You do not see any signing
  or plumbing code.
- `event.payload` is a plain dict. Underwrite does not impose a schema
  on payload shape — keep it simple and document it in your service's
  docstring.

## Step 3 — write a tiny driver

Create `greeter/run_demo.py`:

```python
"""Drive a Greeter end-to-end against an in-memory runtime."""

from __future__ import annotations

from underwrite.runtime import Runtime

from greeter.service import Greeter


def main() -> None:
    with Runtime() as runtime:
        greeter = Greeter(name="greeter", bus=runtime.bus, store=runtime.store)
        runtime.register("greeter")
        runtime.start(["audit"])

        runtime.publish("user.greeted", {"name": "priya"})
        runtime.publish("user.greeted", {"name": "arjun"})


if __name__ == "__main__":
    main()
```

Run it:

```bash
python -m greeter.run_demo
```

You should see two `user.greeted_back` events flow through the audit
service. The runtime's audit mirror writes every event to the audit
log; the `dlq` count should be `0`.

## Step 4 — add a test

Tests live in `tests/test_<service>.py`. Create `tests/test_greeter.py`:

```python
"""Tests for the Greeter nano-service."""

from __future__ import annotations

from underwrite.message import Message
from underwrite.runtime import Runtime

from greeter.service import Greeter


def test_greeter_emits_greeted_back() -> None:
    captured: list[Message] = []

    with Runtime() as runtime:
        greeter = Greeter(name="greeter", bus=runtime.bus, store=runtime.store)
        runtime.register("greeter")
        runtime.start(["audit"])

        def _capture(msg: Message) -> None:
            captured.append(msg)

        # Spy on the bus by subscribing to the outgoing event type.
        runtime.bus.subscribe("user.greeted_back", _capture)

        runtime.publish("user.greeted", {"name": "priya"})
        runtime.bus.flush()

    assert len(captured) == 1
    assert captured[0].payload == {
        "name": "priya",
        "message": "hello, priya!",
    }
```

Run the suite:

```bash
pytest tests/test_greeter.py -v
```

You now have a working service, a driver script, and a unit test —
about 50 lines of code total.

## What you learned

- `Core` is the only base class you need. Implement `handle(event)`,
- call `self.emit(...)` to publish, and the runtime handles signing,
- tracing, metrics, idempotency, and the DLQ.
- `Runtime` is a context manager. Use it in `with` blocks so the bus,
- executor, and tracer shut down cleanly.
- Tests run against an in-memory `Runtime()` with no broker, no
- database server, and no cluster.

## Where to go next

- [Tutorial: the event bus](TUTORIAL_EVENT_BUS.md) — see how
  publish, subscribe, authz, idempotency, and DLQ interact in detail.
- [Tutorial: custom nano-services](TUTORIAL_CUSTOM_NANO.md) — the
  patterns used by the 34 wired services, distilled.
- [Tutorial: pluggable backends](TUTORIAL_PLUGINS.md) — swap the
  store, bus, or tracer for your own implementation.
- [Architecture](architecture.md) — diagrams of every layer.