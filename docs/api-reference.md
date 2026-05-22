# API Reference

## Package: `underwrite`

### Core Classes

| Class | Module | Description |
|-------|--------|-------------|
| `Runtime` | `__runtime__` | Service lifecycle manager |
| `Configuration` | `__config__` | JSON/env-driven configuration |
| `NanoService` | `services.base` | Abstract base for all services |
| `Event` | `__events__` | Typed event envelope |
| `EventType` | `__events__` | Canonical event type constants |

### Event Bus

| Class | Module | Description |
|-------|--------|-------------|
| `EventBus` | `__bus__` | Abstract event bus interface |
| `LocalBus` | `__bus__` | In-process thread-pool implementation |

### State Store

| Class | Module | Description |
|-------|--------|-------------|
| `Store` | `__store__` | Abstract store interface |
| `MemoryStore` | `__store__` | In-memory dict-backed store |
| `FileStore` | `__store__` | Filesystem JSON-backed store |
| `PostgresStore` | `__store__` | PostgreSQL-backed store |

### Infrastructure

| Class | Module | Description |
|-------|--------|-------------|
| `Identity` | `__identity__` | Ed25519 keypair for service attestation |
| `AccessControl` | `__authz__` | Policy evaluation + signature verification |
| `SagaOrchestrator` | `__saga__` | Distributed transaction coordination |
| `CircuitBreaker` | `__circuit__` | Failure isolation with retry |
| `Tracer` | `__tracer__` | Distributed span tracing |
| `MetricsCollector` | `__metrics__` | Counters, timers, gauges |
| `HealthRegistry` | `__health__` | Component health checks |
| `DeadLetterQueue` | `__bus__` | Failed event storage |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `UnderwriteError` | Base exception |
| `ConfigurationError` | Invalid configuration |
| `ServiceNotFoundError` | Unknown service name |
| `IdentityError` | Key or signature issues |
| `BusError` | Event bus failures |
| `StoreError` | Storage layer failures |
| `ProtocolError` | Domain rule violations |
| `InfeasibleOperationError` | Business rule prevents operation |
| `InvariantViolationError` | State invariant broken |
| `UnknownUserError` | Unknown protocol participant |

## CLI Commands

```
underwrite init [--config PATH]     Generate default config
underwrite run [--config PATH]      Start enabled services
underwrite list                     List registered services
underwrite identity SERVICE_NAME    Show service identity
underwrite health                   Runtime health check
underwrite dlq                      View dead letter queue
underwrite metrics                  Metrics snapshot
underwrite migrate                  Apply store migrations
```
