# Design Decisions

## 1. Nano-Service Architecture

**Context:** The underwrite platform needs to model 28 distinct business domains (mechanism, risk, fraud, compliance, decision, payment, collection, etc.) in a single Python process while preserving the logical separation normally achieved with microservices.

**Decision:** Decompose the monolith into nano-services — lightweight `NanoService` subclasses that communicate exclusively via an in-process event bus. Each service owns its slice of domain logic, has its own `Identity` for signing events, and can be independently enabled, disabled, or deployed (via `Runtime.start(["risk", "fraud"])` or CLI `underwrite run risk fraud`).

**Alternatives Considered:**
- **True microservices (HTTP/gRPC):** Network overhead, serialization cost, deployment complexity, no shared memory for delegation graph. Rejected for a 28-service footprint where ~80 % of interactions are sub-millisecond state queries.
- **Monolithic service with internal modules:** Tempting but eliminated by the requirement that services be independently deployable to serverless platforms (Modal) and independently testable. Module-level separation does not enforce the event-driven contract.
- **Actor model (Akka, Thespian):** Over-engineered for a single-process Python system. The actor lifecycle and supervision primitives overlap with what a simple `ThreadPoolExecutor` + `ServiceSupervisor` provide.

**Consequences:**
- (+) Zero serialization overhead: event dispatch is a function call through the bus.
- (+) Synchronous execution guarantees: `emit()` returns after all subscribers have processed the event (or failed to DLQ). No eventual consistency between services within the same process.
- (+) Independent deployability: `underwrite run risk` starts only the risk service.
- (-) No network isolation: a crash in one service takes down the process. Mitigated by `ServiceSupervisor` for per-service restart and automated crash recovery.
- (-) Single-process bottleneck: all services share the same GIL. Mitigated by `ThreadPoolExecutor` for concurrent handler dispatch (configurable per service).

---

## 2. Event-Driven Communication with Typed Enum

**Context:** 28 services need to exchange ~80 distinct event types. A shared vocabulary is essential for wiring, documentation, and tooling.

**Decision:** Define every event type as a member of a single `EventType` string enum in `events.py`. The `WIRING` dict in `handler.py` maps each event type to its subscriber list, acting as a centralized, declarative routing table.

**Alternatives Considered:**
- **Distributed contract (Protobuf / Avro schema registry):** Adds a build step, code generation, and a runtime dependency on a schema registry. Overkill for 80 types in a single Python package.
- **Decentralized event registries (each service defines its own events):** Would make cross-service wiring implicit and harder to audit. The `WIRING` dict provides a single-file view of all communication paths.
- **Class-based event types (subclasses of Event):** Adds import overhead and prevents the clean `EventType.QUOTE_CALCULATED.value` pattern used throughout.

**Consequences:**
- (+) Single source of truth: adding a new event type requires one enum entry and one wiring row.
- (+) IDE completions: `EventType.RISK_SCORED` is discoverable and refactorable.
- (-) Tight coupling of enum: every service imports the same module. A change to one event type requires rebuilding the package (acceptable for a monorepo).
- (-) No versioning built into the enum: payload schema changes must be managed separately via `schema.py` (the `SchemaRegistry`).

---

## 3. Ed25519 Signatures on Events

**Context:** The platform certifies financial events (loan origination, disbursement, default). Non-repudiation and provenance are audit requirements.

**Decision:** Every `Event` carries a cryptographic signature created by the emitting service's `Identity` (Ed25519 private key). The `AccessControl` system verifies the signature in `assert_verified()` before the event reaches any subscriber. The signature is computed over `event_id:timestamp:event_type:payload_json(sorted)`.

**Alternatives Considered:**
- **HMAC with shared secret:** Simpler but lacks non-repudiation — any service holding the shared secret could forge events from another service.
- **JWT:** Adds complexity (token expiry, refresh, standard claims) without benefit. Ed25519 provides the same guarantee with fewer moving parts.
- **No signatures (trust all intra-process events):** Fastest but unacceptable for audit. Signed events provide cryptographic proof that survives log export.

**Consequences:**
- (+) Cryptographic provenance: every event can be independently verified against the emitter's public key.
- (+) Non-repudiation: the emitter cannot deny having emitted an event.
- (-) Signing/verification overhead: ~100 µs per operation. Acceptable for financial workloads where event throughput is <10k/s.
- (-) Key management dependency: services need access to their private key. Mitigated by `SecretsManager` with `EnvSecretsBackend`, `VaultSecretsBackend`, and `AwsSecretsBackend`.
- (-) `cryptography` library mandatory: adds a C-extension build dependency.

---

## 4. Pluggable Store Abstraction

**Context:** Different deployment environments need different persistence: in-memory for tests, filesystem for dev, Postgres for production, read replicas for CQRS.

**Decision:** Define a `Store` ABC with `get`/`set`/`delete`/`exists`/`keys`. Implement `MemoryStore`, `FileStore` (JSON files with atomic write), and `PostgresStore` (psycopg2 with connection pooling, circuit breaker, and retry). The `CQRSStore` wrapper separates read and write stores with read-store invalidation on write.

**Alternatives Considered:**
- **SQLAlchemy ORM:** Overkill for a key-value interface. The store abstraction is intentionally limited to `(key, value)` to keep all backends swappable.
- **Single Postgres-only store:** Locks out in-memory test usage and filesystem-based local development.
- **Custom query interface:** Every store would need to implement SQL parsing. The simple `keys(pattern)` with substring matching is sufficient for the delegation graph's needs.

**Consequences:**
- (+) Backend-agnostic: tests use `MemoryStore`, CI uses `FileStore`, production uses `PostgresStore` — zero code changes.
- (+) CQRS support: `CQRSStore(WriteStore, ReadStore)` with automatic read invalidation on `set()`.
- (-) Limited to key-value operations: no relational queries, no joins, no transactions across keys. Services must manage their own consistency.
- (-) `keys()` is O(n) on `FileStore` (directory traversal) and `MemoryStore` (full scan). Acceptable for <100k keys.

---

## 5. Saga Pattern for Transactions

**Context:** Loan origination spans multiple services (risk → fraud → compliance → document → disbursement). A failure in any step must roll back previous steps.

**Decision:** Implement a `SagaOrchestrator` that executes steps sequentially with compensating events on failure. Each step is idempotent via store-backed idempotency keys (`saga_step:{saga_id}:{step_index}`). Saga state is persisted to the store for crash recovery. Services implement `emit()` for both forward and compensating actions.

**Alternatives Considered:**
- **Distributed transactions (XA / two-phase commit):** Adds a transaction coordinator, database lock contention, and is impractical across different store backends.
- **Outbox pattern with CDC:** Appropriate for跨-service transactions with Kafka, but adds infrastructure complexity not justified in a single-process system.
- **Choreographed sagas (each service manages its own compensation):** Harder to reason about, debug, and test. The central orchestrator provides a single execution trace.

**Consequences:**
- (+) Crash recovery: incomplete sagas are replayed on restart via `replay_saga()`.
- (+) Compensating events are explicit: each step defines both forward and rollback event types and payloads.
- (+) Per-step idempotency: safe to retry after failure at any step.
- (-) Eventual consistency: there is a window between step execution and completion where the system is partially committed.
- (-) No ACID guarantees: sagas provide "compensating transaction" semantics, not atomicity.
- (-) Compensation logic must be implemented per service: adding a saga step requires both forward and backward handling.

---

## 6. In-Process Bus (LocalBus)

**Context:** Services run in the same process and need synchronous, low-latency event delivery.

**Decision:** Implement `LocalBus` — a synchronous, thread-safe in-process pub-sub bus using `threading.RLock` for concurrency. Supports synchronous dispatch (same thread), thread-pool dispatch (configurable `max_workers`), rate limiting (token bucket), per-subscriber circuit breaking, dead-letter queue with optional store persistence, and idempotency guard. An `AsyncLocalBus` variant uses `asyncio.Queue` for async contexts.

**Alternatives Considered:**
- **Redis Pub/Sub / SQS / Kafka:** Adds network dependency, serialization overhead, latency, and operational complexity. Not needed when all services share a process.
- **ZeroMQ / Nanomsg:** In-process is not their primary use case; they introduce a socket layer even for same-process communication.
- **MPMC queues (concurrent.futures):** Too low-level — no subscription model, no routing, no circuit breaker, no DLQ.

**Consequences:**
- (+) Minimal latency: event dispatch is a dict lookup + function call (sub-µs).
- (+) Deterministic ordering within a single thread: synchronous dispatch preserves event order for single-threaded subscribers.
- (+) Rich built-in features: rate limiter, circuit breaker, DLQ, idempotency guard — no external services needed.
- (-) Single-process only: cannot distribute services across machines. The `EventBus` ABC exists for future SQS/Modal backends.
- (-) Thread-pool dispatch loses ordering guarantees: concurrent handlers may process events out of order.

---

## 7. CQRS via CQRSStore

**Context:** The delegation graph is read-heavy (every quote, origination, and path query reads graph state) and write-sparse (only mechanism service writes). A read replica can reduce contention.

**Decision:** Implement `CQRSStore` that wraps a write `Store` and a read `ReadStore`. Writes go to the primary store; reads go to the read store. On `set()`, the read store key is deleted (lazy invalidation) so the next read fetches from the write store. The `postgres` store backend can use a read replica for the read store.

**Alternatives Considered:**
- **Single store:** Simple, but read-heavy workloads contend with writes on the same connection pool/table.
- **Eventual-consistency read replica:** Postgres streaming replication as read store. Requires `CQRSStore` to be configured with different DSNs for read and write.
- **Separate read model (materialized views):** Overkill for key-value access. The current approach is a lightweight compromise.

**Consequences:**
- (+) Reduced write-contention on read path: reads go to a separate store (memory or replica).
- (+) Backend-agnostic CQRS: works with any combination of MemoryStore, FileStore, PostgresStore.
- (-) Read-after-write inconsistency: the read store delete is asynchronous relative to the write. A read immediately after a write may see stale data. Mitigated by the fact that most reads are from the same service that wrote (cached in memory via `StatefulService`).
- (-) Lazy invalidation means the first read after a write is slow (misses the read store cache).

---

## 8. Configuration via Pydantic + JSON + Env Overrides

**Context:** The runtime needs per-environment configuration (dev/staging/prod) with sensible defaults and validation.

**Decision:** Define a `Configuration` Pydantic model with nested configs for all subsystems (`BusConfig`, `StoreConfig`, `LoggingConfig`, `IdentityConfig`, `AuthzConfig`, `MetricsConfig`, etc.). Loading cascade: built-in defaults → JSON file (`config.{env}.json`) → env vars (`UNDERWRITE_*`). Validation is enforced at load time by Pydantic field validators.

**Alternatives Considered:**
- **YAML:** While more readable, YAML has security concerns (arbitrary code execution via `!!python/` tags) and no standard Python type coercion. JSON is safe, universal, and readable enough for the config surface area.
- **TOML:** Python's stdlib only added `tomllib` in 3.11. JSON has broader tooling support.
- **Only environment variables:** Becomes unwieldy with 30+ config keys. The JSON file serves as a structured, documented default.
- **Dynaconf / OmniConf:** Additional dependency for marginal benefit over Pydantic's built-in `model_validate` and `model_dump`.

**Consequences:**
- (+) Schema validation at load time: typos and type mismatches are caught immediately.
- (+) Layered overrides: JSON for environment, env vars for secrets and per-deployment tweaks.
- (+) Self-documenting: the Pydantic model serves as the schema documentation.
- (-) JSON files in production require config management (volume mounts, ConfigMaps, or a config service).
- (-) No built-in hot-reload: config changes require a process restart.

---

## 9. Thread Pool Dispatch in NanoService

**Context:** Some handlers perform I/O (store reads, model inference, external API calls). Synchronous dispatch blocks the bus and other subscribers.

**Decision:** `NanoService` accepts a `max_concurrent` parameter. When > 0, `__dispatch` submits the handler to a `ThreadPoolExecutor` instead of executing on the calling thread. The `LocalBus` also supports `max_workers` for cross-service concurrency. The bus's `CircuitBreaker` and `DeadLetterQueue` operate at the subscriber level regardless of dispatch mode.

**Alternatives Considered:**
- **Asyncio everywhere:** Would require all services to be async, which is a significant refactor. The hybrid approach (sync services, optional thread pool) avoids async adoption friction.
- **Gevent / eventlet monkey-patching:** Implicit concurrency that makes reasoning about state harder. Explicit `ThreadPoolExecutor` is more controllable.

**Consequences:**
- (+) No head-of-line blocking: a slow fraud check does not block the risk scoring handler.
- (+) Configurable per-service: read-heavy services run synchronously; inference-heavy services get a thread pool.
- (-) Ordering guarantees lost: concurrent handlers may process events in a different order than they were published. Each service must be designed to handle out-of-order events (idempotency helps).
- (-) Thread safety required: all shared state must be protected by locks. The `state_lock` pattern in `StatefulService` addresses this.

---

## 10. Pyproject.toml Only (PEP 621)

**Context:** Modern Python packaging standardizes on `pyproject.toml` as the single build configuration file.

**Decision:** Define all metadata, dependencies, and tool configuration in `pyproject.toml`. Version is generated by `setuptools-scm` from git tags. There is no `requirements.txt`, `setup.py`, `setup.cfg`, or `MANIFEST.in`. Tool configs for pytest, ruff, mypy, bandit, and mutmut are inlined in `pyproject.toml`.

**Alternatives Considered:**
- **requirements.txt + setup.py:** Legacy approach, duplicates dependency information. The `uv.lock` lockfile replaces `requirements.txt` for deterministic installs.
- **Poetry / PDM:** Feature-rich but introduce their own lockfile format and CLI. `setuptools-scm` + `uv` is lighter and more standard.
- **Flit / Hatch:** Also PEP 621-compliant, but `setuptools` remains the most widely supported backend for C-extensions (`cryptography`).

**Consequences:**
- (+) Single file for all config: no fragmentation across `setup.py`, `.ruff.toml`, `mypy.ini`, etc.
- (+) Standard tool config: any PEP 621-compliant tool can read `pyproject.toml`.
- (-) Tool-specific features may be limited: some tools have richer config in their own files.

---

## 11. Strategy Pattern for Risk Scoring

**Context:** The risk scoring model can be a heuristic, a JSON-serialized linear model, a joblib-serialized sklearn model, or a plugin-loaded third-party model. The choice must be configurable and extensible without code changes.

**Decision:** Implement `RiskScoringStrategy` ABC with concrete strategies: `HeuristicStrategy` (fallback), `JsonModelStrategy` (parse `coef_`/`intercept_` from JSON), `JoblibModelStrategy` (wrap sklearn model). The `StrategyRegistry` provides plugin-like registration by name. The `RiskModel` facade loads the appropriate strategy based on the model file path. Joblib loading is gated behind `UNDERWRITE_ALLOW_JOBLIB` for security.

**Alternatives Considered:**
- **Single model loader with if/else branches:** Harder to extend. The strategy pattern allows third-party plugins to register custom strategies.
- **MLflow / model registry client:** Adds a network dependency and a heavyweight client. The current approach is file-based and offline.
- **ONNX runtime:** More general, but introduces a large dependency. sklearn is sufficient for the current feature set.

**Consequences:**
- (+) Pluggable: new strategies (XGBoost, LightGBM, neural network) can be registered without modifying existing code.
- (+) Secure by default: joblib (pickle) is disabled unless explicitly allowed, mitigating arbitrary code execution risk.
- (+) SHA-256 integrity verification: model files are checked against a hash before loading.
- (-) Limited to `predict(principal, term)` signature: more complex models requiring engineered features need a custom strategy.

---

## 12. Circuit Breaker + Retry Pattern

**Context:** `FileStore` and `PostgresStore` interact with I/O subsystems that can fail transiently (disk full, connection timeout, deadlock). Without resilience, a single I/O failure propagates to all services using the store.

**Decision:** Implement `CircuitBreaker` (CLOSED → OPEN → HALF_OPEN state machine) and `RetryPolicy` (exponential backoff with jitter). `FileStore` wraps every I/O operation in `CircuitBreaker.call()` with configurable threshold and recovery timeout. `PostgresStore` uses both `CircuitBreaker` (per-op) and `RetryPolicy` (per-op with 2 retries, 50ms base delay). The bus has a separate `CircuitBreaker` per subscriber for event-handler failures.

**Alternatives Considered:**
- **Try/except everywhere:** Ad-hoc, no centralized state. A circuit breaker provides a fails-fast mechanism that prevents cascading failures.
- **Tenacity / backoff library:** External dependencies with more features than needed. The in-house implementation is ~130 lines and covers the specific use case (consecutive failure threshold, half-open probe).
- **Resilience4j (Java port):** Over-engineered for Python; the in-house implementation is simpler and sufficient.

**Consequences:**
- (+) Fast failure: when the circuit is OPEN, calls fail immediately without I/O.
- (+) Automatic recovery: after the cooldown, a probe request tests if the subsystem has recovered.
- (-) Additional latency on failure: the retry policy waits between attempts, which can back up the handler thread pool.
- (-) State mismatch: the `CircuitBreaker` in `bus.py` and the one in `circuit.py` are separate implementations. The bus's per-subscriber circuit breaker is hardcoded (no configuration), while the store's circuit breaker is configurable. This duplication should be consolidated.
