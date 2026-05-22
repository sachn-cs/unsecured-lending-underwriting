# Architecture

## Nano-Service Model

Each nano-service is a Python class extending `NanoService` (defined in `services/base.py`). Services:

1. Subscribe to event types via `subscribe()` in their constructor
2. Receive events through `__dispatch()` which handles cross-cutting concerns
3. Implement `handle(event)` for domain logic
4. Emit events via `emit()` with automatic Ed25519 signing

## Event Flow

```
Service A                    Event Bus                    Service B
    |                           |                             |
    |--- emit("loan.originated") -->|                         |
    |                           |--- dispatch(event) -------->|
    |                           |    |                        |
    |                           |    +-- authz check          |
    |                           |    +-- idempotency guard    |
    |                           |    +-- tracing span         |
    |                           |    +-- metrics              |
    |                           |    +-- saga tracking        |
    |                           |    +-- handle(event)        |
```

## Cross-Cutting Concerns

Injected into each service at construction:

| Concern | Module | Mechanism |
|---------|--------|-----------|
| Authz | `__authz__` | Policy evaluation + Ed25519 signature verification |
| Tracing | `__tracer__` | Span lifecycle with parent/child relationships |
| Metrics | `__metrics__` | Counters, timers, gauges with tag dimensions |
| Saga | `__saga__` | Forward execution + compensating rollback |
| Idempotency | `__bus__` | Duplicate event detection by (service, event_id) |

## State Store

All services share a `Store` abstraction with backends:

- **MemoryStore** — `dict`-backed, thread-safe, ephemeral
- **FileStore** — JSON files on disk, thread-safe, optional circuit breaker
- **PostgresStore** — connection-pooled SQL, with statement timeout

CQRS is supported via separate read/write stores.
