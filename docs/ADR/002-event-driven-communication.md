# ADR 002: Event-Driven Communication with Typed Events

**Status**: Accepted

## Context

Thirty-four nano-services need to exchange approximately 132 distinct event types. A shared, discoverable, and enforceable vocabulary is essential for wiring, documentation, tooling, and audit. Events also need to carry tracing context and fit into the domain's financial-audit requirements.

The event type enum is defined at `underwrite/message.py:140` (`Type`). The event envelope is the `Message` dataclass at `message.py:28`. The subscriber wiring lives in `handler.py:95` as the `WIRING` dict.

## Problem

How should services discover, define, and route events without creating implicit coupling or requiring a schema registry?

## Decision

1. **Single `Type` string enum**: Every event type is a member of `Type` (`message.py:140`), following the convention `<domain>.<action>[.<outcome>]` (e.g., `loan.originated`, `fraud.velocity.flag`, `npa.dlg.triggered`). The enum is the single source of truth — adding a new event type requires exactly one new enum member.

2. **Immutable event envelope**: `Message` (`message.py:28`) is a frozen, slotted dataclass carrying:
   - `event_id` (UUID v4), `event_type`, `source`, `source_key` (Ed25519 public key)
   - `timestamp` (ISO-8601 UTC), `payload` (dict, ≤1 MB serialized, ≤1000 keys)
   - `correlation_id` (UUID chain), `signature` (Ed25519), `trace_id`, `parent_span_id`
   - Validation in `__post_init__` rejects oversized payloads with `ProtocolError`

3. **Declarative routing with `WIRING`**: The `WIRING` dict (`handler.py:95`) maps each event type to its subscriber service IDs. `Runtime.wire()` imports and subscribes each service. This provides a single-file view of all communication paths.

4. **Wildcard subscribe**: Services can subscribe to `"*"` to receive all events (used by `AuditService` and `ReportingService`).

5. **Event types also serve as direct-command channels**: Each service subscribes to its own `service_id` as an event type (e.g., `"mechanism"` receives command events with a `command` field in the payload). This avoids separate RPC mechanisms.

## Alternatives Considered

- **Distributed contract (Protobuf / Avro schema registry)**: Adds a build step, code generation, and runtime dependency on a schema registry. Overkill for 132 types in a single Python package. The `message.py` enum provides the same discoverability with zero infrastructure.

- **Decentralized event registries (each service defines its own events)**: Would make cross-service wiring implicit and harder to audit. With the `WIRING` dict, one grep shows the entire communication graph. Decentralized registration also risks naming collisions.

- **Class-based event types (subclassing `Message`)**: Adds import overhead (each class in its own file or module) and prevents the clean `Type.QUOTE_CALCULATED.value` pattern. The string enum approach allows payload schema validation via `schema.py` without coupling to event type identity.

## Consequences

### Positive
- Single source of truth — adding a new event type requires one enum entry and one wiring row
- IDE completions — `Type.RISK_SCORED` is discoverable and refactorable across the entire codebase
- Built-in payload validation — `Message.__post_init__` enforces size (1 MB) and key count (1000) limits at construction time
- Centralized routing — the `WIRING` dict serves as documentation and can be validated programmatically

### Negative
- Tight coupling to a single enum module — every service imports `message.py`. A change to one event type requires rebuilding the package (acceptable for a monorepo).
- No versioning built into the enum — payload schema changes must be managed separately via `schema.py`. There is no mechanism for coexisting v1 and v2 of the same event type.
- String-based event types are not type-checked at the handler level — a subscriber receives a `dict` payload with no compile-time schema guarantees. Runtime validation is done by each service's `PayloadValidator`.
