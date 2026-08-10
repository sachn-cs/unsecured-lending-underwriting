# ADR 001: Nano-Service Architecture

**Status**: Accepted

## Context

The `underwrite` platform models 28 distinct business domains (mechanism, risk, fraud, compliance, decision, payment, collection, NPA, collateral, recovery, governance, identity, etc.) that must coexist in a single Python process while preserving the logical separation normally associated with microservices.

The codebase is a single Python package (`pyproject.toml` defines the package as `underwrite`). All source lives under `underwrite/` with services under `underwrite/services/`. The `NanoService` base class is at `services/base.py:93`.

## Problem

How should these 28 business domains be structured for independent development, testability, and future deployability without the operational overhead of a distributed system?

## Decision

Decompose the monolith into **nano-services** — lightweight `NanoService` ABC subclasses that communicate exclusively through an in-process event bus (`EventBus` at `bus.py:426`).

Each `NanoService` (`services/base.py:93`):
- Owns exactly one domain boundary (e.g., `fraud`, `pricing`, `disbursement`)
- Has its own `Identity` (Ed25519 keypair at `identity.py:30`) for signing emitted events
- Persists state through a `Store` ABC (`store.py:52`)
- Implements a single `handle(event: Event) -> None` method
- Can be independently started via `Runtime.start(["risk", "fraud"])` or `underwrite run risk`
- Supports optional `max_concurrent` thread-pool dispatch for I/O-bound handlers

Cross-cutting concerns (authz, tracing, metrics, idempotency, saga, supervision) are injected transparently in `NanoService.__dispatch()` and `__handle_event()` at `services/base.py:291-317`.

Wiring is declarative: the `WIRING` dict in `handler.py:80` maps each `EventType` to its subscriber list. On startup, `Runtime.wire()` iterates this map and subscribes each listed service.

## Alternatives Considered

- **True microservices (HTTP/gRPC)**: Network overhead, serialization cost, and deployment complexity. Rejected because ~80% of interactions across 28 services are sub-millisecond state queries (e.g., `graph_credit_limit`). The nano-service model keeps them in-process with zero serialization overhead.

- **Monolithic service with internal modules**: Module-level separation does not enforce an event-driven contract. Nothing prevents a fraud module from calling a pricing module's internal function, creating implicit coupling. The `NanoService` ABC enforces that the only communication path is `EventBus.publish()`.

- **Actor model (Akka, Thespian)**: Over-engineered for a single-process Python system. The actor lifecycle and supervision primitives overlap with what `ThreadPoolExecutor` + `ServiceSupervisor` (`supervisor.py:15`) already provide.

## Consequences

### Positive
- Zero serialization overhead — event dispatch is a function call through the bus
- Synchronous execution guarantees — `emit()` returns after all subscribers have processed (or DLQ'd). No eventual consistency within the process.
- Independent deployability — `underwrite run risk` starts only the risk service. Any service can be extracted to its own process when needed by swapping the `EventBus` backend.
- Testability — services are tested in isolation by subscribing them to synthetic events
- Auditability — every state change is a published, signed event captured by `AuditService`

### Negative
- No network isolation — a crash in one service takes down the entire process. Mitigated by `ServiceSupervisor` auto-restart with exponential backoff.
- Single-process bottleneck — all services share the same GIL. Mitigated by `ThreadPoolExecutor` for concurrent handler dispatch (configurable per service via `max_concurrent`).
- `Runtime.runtime.py` and `MechanismService` may grow large enough to violate SRP — split out when they cross ~500 lines, tracked in `docs/REFACTORING_PLAN.md`.
