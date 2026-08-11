# Glossary

| Term | Definition |
|------|------------|
| **Nano-service** | Lightweight, independently deployable service extending `Core` ABC (`services/base.py:149`). Each owns a single domain boundary and communicates only through typed events. |
| **Event Bus** | In-process pub/sub backbone (`bus.py:426` — `EventBus` ABC). `LocalBus` is the default synchronous, thread-safe implementation. `AsyncLocalBus` provides an `asyncio` variant. |
| **Message** | Typed envelope (`message.py:28` — `Message` dataclass, frozen + slots). Carries `event_id`, `event_type`, `source`, `source_key` (Ed25519 public key), `timestamp`, `payload` (≤1 MB, ≤1000 keys), `correlation_id`, `signature` (Ed25519), `trace_id`, `parent_span_id`. |
| **Saga** | Distributed transaction pattern (`saga.py:68`). An ordered list of `SagaStep`s with forward actions and compensating rollbacks. Coordinated by `SagaOrchestrator` with store-backed persistence and idempotent replay. |
| **Delegation Graph** | Protocol state machine (`services/mechanism/graph.py` — `DelegationGraph`). Tracks seeds, users, delegations, loans, and edges. Pure domain model with no infrastructure dependencies. |
| **Seed** | Root protocol participant with a `base_budget` (e.g., a bank providing capital). Added via `add_seed(user, budget)`. Seeds have unlimited credit limited only by their budget. |
| **Credit Limit** | Available borrowing capacity: `budget + earned - outgoing_delegations`. For non-seeds, `budget` equals the incoming delegation amount. |
| **NPA** | Non-Performing Asset — RBI classification for delinquent loans. Buckets: standard (0-90d), substandard (91-180d), doubtful (181-360d), loss (>360d). Classified by `NPAService` (`services/npa.py`). |
| **DLG** | Delegated Loss Guarantee — trigger at 120+ days overdue (`services/npa.py:27`). Emits `npa.dlg.triggered` event. |
| **Circuit Breaker** | Failure isolation pattern with three states: CLOSED (normal), OPEN (failing fast), HALF_OPEN (probing recovery). Two implementations: `bus.py:223` (per-subscriber, hardcoded threshold of 5, 60s cooldown) and `circuit.py` (configurable, available for callers who want to wrap their own I/O). |
| **Sqlite Store** | The only persistence backend shipped with `underwrite`. Backed by the Python standard library `sqlite3` module. Configurable via `Configuration.store.path` and `Configuration.store.busy_timeout`. |
| **DLQ** | Dead Letter Queue — bounded storage for failed events (`bus.py:48` — `DeadLetterQueue`). Default 10,000 entries, optional `Store` persistence, supports replay via `replay()`. |
| **LTV** | Loan-to-Value ratio — collateral requirement set at 75% (`services/collateral.py:19`). |
| **KYC/AML** | Know Your Customer / Anti-Money Laundering. Validated by `ComplianceService` (`services/compliance.py`): PAN format `^[A-Z]{5}[0-9]{4}[A-Z]$`, Aadhaar format `^\d{12}$`. |
| **OTLP** | OpenTelemetry Protocol — trace/metric export via gRPC. `OtlpSpanExporter` in `tracer.py` exports spans when `tracing.exporter == "otlp"`. Optional dependency: `underwrite[otlp]`. |
| **Ed25519** | Elliptic curve signing algorithm (Curve25519) used for event signatures. Implemented via `cryptography` library in `identity.py`. Every `Message` is signed over `event_id:timestamp:event_type:payload` and verified by `AccessControl.verify_signature()`. |
| **Idempotency Guard** | Duplicate event detection (`bus.py:376`). Tracks `(handler_id, event_id)` pairs, bounded at 100,000 IDs per handler. Evicts oldest entries via FIFO. |
| **Rate Limiter** | Token-bucket algorithm (`bus.py:284`). Per-subscriber rate limiting in `LocalBus`. `DistributedRateLimiter` extends this with a `Store` backend for cross-process coordination. |
| **Supervisor** | `ServiceSupervisor` (`supervisor.py:15`). Tracks consecutive failures per service, supports auto-restart with exponential backoff (up to 60s), and marks permanently unhealthy after `max_restarts` (default 3). |
| **WIRING** | Static dict (`handler.py:95`) mapping each `Type` to its list of subscriber service IDs. Acts as a centralized, declarative routing table. |
| **MechanismService** | Core protocol service (`services/mechanism.py`). Owns `DelegationGraph`, processes commands (`add_seed`, `add_user`, `originate`, `repay`, `default`, `revoke`, `quote`). |
| **SagaStep** | One step in a saga (`saga.py:38`). Has `name`, `forward_event_type`/`forward_payload` (the action), and `compensate_event_type`/`compensate_payload` (the rollback). |
