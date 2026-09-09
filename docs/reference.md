# API reference

This page is the canonical reference for the `underwrite` Python API.
Every public symbol is listed with its parameters, return type, and a
runnable example. Use the table of contents on the right to jump to a
specific module.

!!! info "Scope"
    The reference covers the stable public surface — the modules you
    import from `underwrite`. Internal helpers and underscored names
    are out of scope; they change without notice between minor
    versions.

## Runtime entry point

### `underwrite.runtime.Runtime`

```python
class Runtime(config: Configuration | None = None, *, readonly: bool = False)
```

The orchestrator that wires every nano-service in the runtime together.
`Runtime` is the only object most users need to instantiate directly.

**Parameters**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `config` | `Configuration \| None` | `None` | An explicit configuration object. When `None`, the runtime loads `underwrite.json` from the current directory or the path in `UNDERWRITE_CONFIG`. |
| `readonly` | `bool` | `False` | Construct the runtime without an Ed25519 identity, authz, or services. Useful for read-only `Sqlite` inspection scripts. |

**Context manager**

`Runtime` is a context manager. Use it inside `with` blocks so the bus,
executor, and tracer shut down cleanly:

```python
from underwrite.runtime import Runtime

with Runtime() as rt:
    rt.start(["mechanism", "audit"])
    rt.publish("mechanism", {"command": "ping"})
    print(rt.health.status())
```

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `start(service_names=None)` | `None` | Spin up the named services (or every wired service if `None`). |
| `stop()` | `None` | Stop every service, drain the bus, and shut down the executor. |
| `restart_failing_services()` | `list[str]` | Ask the supervisor to restart services the breaker marked unhealthy. |
| `register(name, identity=None)` | `Core` | Register a service instance by name. |
| `get(name)` | `Core \| None` | Fetch a registered service by name. |
| `publish(event_type, payload, correlation_id="")` | `str` | Publish a domain event. Returns the new event id. |
| `publish_as(source, event_type, payload, ...)` | `str` | Publish as an explicit source identity (rarely needed). |
| `identity_for(service_id)` | `Keypair` | Look up the Ed25519 keypair for a service. |
| `sign_outbound_event(event_type, payload, correlation_id)` | `Message` | Build a signed `Message` without dispatching it. |
| `replay_saga(saga_id)` | `bool` | Replay a saga from the store. |
| `health` | `Checks` | Aggregate subsystem health registry. |

**Attributes**

| Attribute | Type | Description |
|-----------|------|-------------|
| `bus` | `EventBus` | The wired event bus (`LocalBus` by default). |
| `store` | `Store` | The wired state store (`Sqlite` by default). |
| `authz` | `AccessControl \| None` | Authorization engine, or `None` when disabled. |
| `metrics` | `Collector \| None` | Metrics collector, or `None` when disabled. |
| `tracer` | `Tracer \| None` | Tracer, or `None` when disabled. |
| `saga` | `Orchestrator \| None` | Saga orchestrator, or `None` when disabled. |
| `config` | `Configuration` | The resolved configuration object. |
| `runtime_identity` | `Keypair \| None` | The runtime's own Ed25519 keypair. |

### `underwrite.runtime.build_runtime(config)`

```python
def build_runtime(config: Configuration) -> Runtime
```

Construct a fully-wired `Runtime` from a `Configuration` without
starting any services. Use this when you need to inject custom
services or rebind the bus before calling `start()`.

## Message envelope

### `underwrite.message.Message`

```python
@dataclass(frozen=True, slots=True)
class Message:
    event_id: str
    event_type: str
    source: str
    source_key: str
    timestamp: str
    payload: dict[str, Any]
    correlation_id: str = ""
    signature: str = ""
    trace_id: str = ""
    parent_span_id: str = ""
```

The unit of communication on the event bus. `Message` is immutable —
mutations go through `dataclasses.replace`.

**`Message.signed(...)` classmethod**

```python
@classmethod
def signed(
    cls,
    keypair: Keypair,
    *,
    type: str,
    source: str,
    source_key: str = "",
    payload: dict[str, Any] | None = None,
    correlation_id: str = "",
    trace_id: str = "",
    parent_span_id: str = "",
) -> Message
```

Construct a fully-signed `Message` ready to publish. The signature is
computed over the canonical signing bytes (`event_id | timestamp |
event_type | source | payload`).

```python
from underwrite.keypair import Keypair
from underwrite.message import Message

kp = Keypair.create("mechanism")
msg = Message.signed(kp, type="mechanism.ping", source="mechanism")
```

**`Message.canonical_sign_bytes()`**

```python
def canonical_sign_bytes(self) -> bytes
```

Return the canonical bytes the signature is computed over. Verification
in `authz.AccessControl.verify_signature` uses the same method, so
signatures are reproducible across processes and Python versions.

**Constants**

| Name | Value | Purpose |
|------|-------|---------|
| `MAX_PAYLOAD_SIZE` | `1_000_000` | Maximum serialized payload in bytes. |
| `MAX_PAYLOAD_KEYS` | `1000` | Maximum top-level keys in the payload. |

## Event bus

### `underwrite.bus.EventBus`

The protocol every event bus implements. `Runtime` injects a
`LocalBus` by default; pluggable backends (SQS, Modal, Redis Streams)
are expected to satisfy the same surface.

```python
class EventBus(Protocol):
    def publish(self, event: Message) -> None: ...
    def subscribe(self, event_type: str, handler: Callable[[Message], None]) -> str: ...
    def unsubscribe(self, subscription_id: str) -> None: ...
    def flush(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
```

### `underwrite.local.LocalBus`

The default in-process bus. Use it directly when you want to drive a
custom runtime:

```python
from underwrite.bus import LocalBus, Queue
from underwrite.store import Sqlite

bus = LocalBus(rate_limit=100.0, store=Sqlite(":memory:"))
bus.start()
```

### `underwrite.dlq.Queue`

The dead-letter queue. Holds failed events with a bounded in-memory
buffer and optional `Store`-backed persistence.

```python
class Queue:
    def __init__(
        self,
        max_records: int = 10000,
        store: Store | Sqlite | None = None,
        sync_interval: int = 10,
    ) -> None: ...
    def put(self, event: Message, error: str, subscriber_id: str) -> None: ...
    def count(self) -> int: ...
    def clear(self) -> None: ...
    def replay(self, bus: Any, max_count: int = 0) -> int: ...
```

### `underwrite.bus.Registry`

Maps event types to handler callables. `LocalBus.subscribe` registers
the handler here and returns a subscription id you can pass to
`unsubscribe`.

## State store

### `underwrite.store.Store`

The protocol every state store implements.

```python
class Store(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any, expires_at: float | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def health(self) -> dict[str, Any]: ...
```

### `underwrite.store.Sqlite`

```python
class Sqlite:
    def __init__(self, path: str = ":memory:") -> None: ...
```

A SQLite-backed store. Pass `:memory:` for ephemeral use, a file path
for persistence. WAL journaling and a `busy_timeout` are enabled by
default.

```python
from underwrite.store import Sqlite

store = Sqlite("./store.db")
store.set("loan:priya-sharma", {"status": "originated"})
```

## Authorization

### `underwrite.authz.AccessControl`

```python
class AccessControl:
    def __init__(self) -> None: ...
    def allow(self, subject: str, resource: str) -> None: ...
    def deny(self, subject: str, resource: str) -> None: ...
    def trust(self, service_id: str, public_key: str) -> None: ...
    def revoke(self, service_id: str) -> None: ...
    def check(self, subject: str, resource: str) -> bool: ...
    def is_trusted(self, source: str) -> bool: ...
    def verify_signature(self, event: Message) -> bool: ...
    def assert_publish(self, event: Message) -> None: ...
    def assert_subscribe(self, source: str, event_type: str) -> None: ...
    def assert_verified(self, event: Message) -> None: ...
    def set_replay_window(self, seconds: float) -> None: ...
```

`AccessControl` is **default-deny**: an empty `AccessControl()` denies
every operation. Use `allow("*", "*")` only when you really mean it.

`verify_signature` returns `False` if:

- the source has not been `trust()`-ed,
- the signature does not match the canonical signing bytes, or
- the timestamp is outside the configured replay window.

`assert_*` variants raise `AuthzError` instead of returning booleans.

## Identity

### `underwrite.keypair.Keypair`

```python
class Keypair:
    @classmethod
    def create(cls, name: str, secrets_manager: Manager | None = None) -> Keypair: ...
    @classmethod
    def load(cls, name: str, secrets_manager: Manager | None = None) -> Keypair | None: ...
    @property
    def name(self) -> str: ...
    @property
    def public_key(self) -> str: ...
    def sign(self, message: str | bytes) -> str: ...
    def rotate(self) -> Keypair: ...
```

`Keypair.create` generates a new Ed25519 keypair. Pass
`secrets_manager` to persist the private key through Vault or AWS
Secrets Manager; otherwise the private key lives only in process
memory.

`sign(message)` accepts either a `str` or `bytes` payload. Strings are
encoded as UTF-8 before signing.

## Configuration

### `underwrite.config.Configuration`

```python
class Configuration(BaseModel):
    store: StoreConfig = ...
    bus: BusConfig = ...
    authz: AuthzConfig = ...
    tracing: TracingConfig = ...
    metrics: MetricsConfig = ...
    logging: LoggingConfig = ...
    saga: SagaConfig = ...
    supervisor: SupervisorConfig = ...
    rate_limit: RateLimitConfig = ...
    dlq: DlqConfig = ...
    exporter: ExporterConfig = ...
    kyc_provider_config: ProvidersConfig = ...
    # ... 17 more sections, see docs/CONFIGURATION.md
```

`Configuration` is a Pydantic v2 model. Use `Configuration.load()` to
read from disk + environment, or `Configuration.merge_file(json_path,
overrides={...})` to layer overrides.

```python
from underwrite.config import Configuration

config = Configuration.load()
config.store.backend = "sqlite"
config.store.path = "/var/lib/underwrite/store.db"
```

## Metrics

### `underwrite.metrics.Collector`

```python
class Collector:
    def __init__(self, max_metrics: int = 10000) -> None: ...
    def increment(self, name: str, value: float = 1.0, tags: dict[str, str] | None = None) -> None: ...
    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None: ...
    def timer(self, name: str, value_ms: float, tags: dict[str, str] | None = None) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...
```

The collector bounds the cardinality of each metric family to
`max_metrics // 3`. When the bound is exceeded, the oldest entries are
evicted.

## CLI

### `underwrite.cli.main`

The `underwrite` console-script entry point. Exposed as the
`underwrite` command:

```bash
underwrite init
underwrite run mechanism audit
underwrite serve --require-auth
```

### `underwrite.cli.load_config`

```python
def load_config(path: str | None = None) -> Configuration
```

Read a `Configuration` from disk, layering any `UNDERWRITE_*` env
vars on top.

## Logging

### `underwrite.logger.configure`

```python
def configure(
    level: str = "INFO",
    fmt: str = "json",
    output: str = "stdout",
    redact_pii: bool = True,
) -> None
```

Configure the runtime logger. `level` is one of `DEBUG`, `INFO`,
`WARNING`, `ERROR`. `fmt` is `json` or `text`. `output` is `stdout`,
`stderr`, or a file path. `redact_pii=True` strips Aadhaar, PAN, and
other token-redacted fields from the log stream before emission.

## PII redaction

### `underwrite.pii.redact`

```python
def redact(value: Any, fields: Iterable[str] | None = None) -> Any
```

Return a deep-copied value with configured PII fields replaced by the
token `***REDACTED***`. Used by the audit, DLQ, and Prometheus exporter.

## Saga

### `underwrite.saga.Orchestrator`

```python
class Orchestrator:
    def __init__(self, store: Store | None = None) -> None: ...
    def register_emitter(self, saga_name: str, emitter: Callable[[str, dict], None]) -> None: ...
    def start(self, saga_name: str, steps: list[Step]) -> Saga: ...
    def replay(self, saga_id: str) -> bool: ...
```

`saga.start` returns a `Saga` instance you can `await` (when running
under an event loop) or poll via `Saga.status()`.

## See also

- [Architecture](architecture.md) — how the modules fit together.
- [Configuration](CONFIGURATION.md) — every key, every default.
- [Environment variables](ENVIRONMENT_VARIABLES.md) — env-var overrides.
- [Source code on GitHub](https://github.com/sachncs/underwrite) — `underwrite/` directory.