# Tutorial: pluggable backends

Underwrite's runtime is intentionally narrow: every cross-cutting
concern is an injected dependency. This page shows you how to swap the
store, the bus, the secrets manager, the tracer, or the metrics
exporter for your own implementation.

The runtime never reaches into `self.bus._internal_thing`. It only
talks to the public protocol. That means you can replace **any**
backend with your own — and the rest of the system keeps working.

## Replacing the store

`Store` is a small protocol with four methods. Implementing it is
typically under fifty lines.

```python
from typing import Any, Protocol


class Store(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any, expires_at: float | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
```

A minimal Redis-backed store:

```python
import json
import redis
from typing import Any


class RedisStore:
    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        self._r = redis.Redis.from_url(url)

    def get(self, key: str) -> Any:
        raw = self._r.get(key)
        return json.loads(raw) if raw else None

    def set(self, key: str, value: Any, expires_at: float | None = None) -> None:
        self._r.set(key, json.dumps(value))
        if expires_at is not None:
            ttl = max(1, int(expires_at - time.time()))
            self._r.expire(key, ttl)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._r.exists(key))

    def health(self) -> dict[str, Any]:
        return {"ok": self._r.ping()}
```

Wire it through the configuration:

```python
from underwrite.config import Configuration, StoreConfig
from underwrite.runtime import Runtime

config = Configuration()
config.store = StoreConfig(backend="custom")  # backend is a hint only

runtime = Runtime.__new__(Runtime)  # bypass the default-construct path
runtime.config = config
runtime.store = RedisStore(url="redis://redis:6379/0")
# ... wire up the rest by hand, or call build_runtime + replace the store
```

In practice you will usually subclass `Runtime` or use
`build_runtime(config)` and patch `runtime.store` after construction.

## Replacing the bus

`EventBus` is the protocol every bus implements:

```python
class EventBus(Protocol):
    def publish(self, event: Message) -> None: ...
    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str: ...
    def unsubscribe(self, subscription_id: str) -> None: ...
    def flush(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
```

A minimal in-memory bus:

```python
import threading
from collections import defaultdict
from underwrite.message import Message
from underwrite.bus import EventBus


class DictBus(EventBus):
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Message], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def publish(self, event: Message) -> None:
        for handler in list(self._subs.get(event.event_type, [])):
            handler(event)

    def subscribe(self, event_type, handler):
        with self._lock:
            self._subs[event_type].append(handler)
            return f"{event_type}:{len(self._subs[event_type])}"

    def unsubscribe(self, subscription_id):
        event_type, _, idx = subscription_id.partition(":")
        with self._lock:
            try:
                self._subs[event_type].pop(int(idx))
            except (KeyError, IndexError, ValueError):
                pass

    def flush(self) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
```

Swap it the same way — build the runtime, then patch `runtime.bus`.

## Replacing the secrets manager

`SecretsManager` is the protocol every secrets backend implements.
The default is `EnvManager`, which reads `UNDERWRITE_*` env vars; the
optional `[vault]` extra ships `VaultManager`; the `[aws]` extra ships
`AWSManager`.

```python
from underwrite.secrets import Manager


class FileManager(Manager):
    def __init__(self, path: str) -> None:
        self._path = path

    def get(self, key: str) -> str | None:
        # implement your lookup
        ...
```

The runtime does not care which implementation is wired. It only calls
`secrets.get(key)`.

## Replacing the tracer

`Tracer` is a simple class. The default `ConsoleTracer` writes spans
to the log; `OTLPTracer` (under the `[otlp]` extra) forwards them to
a collector.

A minimal no-op tracer:

```python
from underwrite.tracer import Tracer


class NullTracer(Tracer):
    def start_span(self, name: str, **attrs):  # type: ignore[override]
        return NullSpan()

    def end_span(self, span) -> None: ...


class NullSpan:
    def set_attribute(self, k, v): ...
    def record_exception(self, exc): ...
```

Disable tracing entirely with `tracing.enabled = false` in the
configuration — most users will not need to write a custom tracer.

## Replacing the metrics exporter

`start_metrics_export(metrics_collector, config)` registers an HTTP
endpoint that Prometheus scrapes. The default is `/v1/metrics`. To
expose Prometheus at the standard `/metrics` path, run a separate
exporter:

```python
from prometheus_client import start_http_server, CollectorRegistry
from underwrite.exporter import PrometheusCollector

registry = CollectorRegistry()
registry.register(PrometheusCollector(runtime.metrics))
start_http_server(9090, registry=registry)
```

This is the recommended pattern in production — you keep your
application metrics endpoint clean and let Prometheus scrape a
separate port.

## When to write your own backend

Write a custom backend when:

- the default does not meet your latency, durability, or operational
  needs (e.g., the default SQLite store cannot meet your throughput),
- you need a vendor-specific integration (Redis, DynamoDB, SQS, Kafka)
  that is not on the optional-extras list,
- you are evaluating Underwrite against an existing infrastructure
  and want to swap one component at a time.

Do **not** write a custom backend when:

- a configuration option would solve your problem (look at
  `Configuration` first),
- the existing optional extra already covers your use case (`[vault]`,
  `[aws]`, `[otlp]`),
- the change is a one-off experiment — extend the existing class
  first.

## Where to go next

- [Architecture](architecture.md) — diagrams of every layer.
- [Configuration](CONFIGURATION.md) — every key, every default.
- [Environment variables](ENVIRONMENT_VARIABLES.md) — env-var overrides.