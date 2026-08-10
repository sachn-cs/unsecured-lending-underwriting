# Frequently Asked Questions

Answers based on the actual underwrite codebase at `underwrite/` and `pyproject.toml`.

---

### 1. What is underwrite?

Underwrite is a **nano-service platform** for unsecured lending underwriting, implementing a Delegated Underwriting Protocol. It provides 28 purpose-built nano-services (risk scoring, fraud detection, KYC/AML, collateral management, loan origination, collections, recovery, governance, and more) that communicate over an in-process event bus with Ed25519 cryptographic attestation. The project is defined in `pyproject.toml` as *"Delegated Underwriting Protocol — nano-service platform for unsecured lending"*.

---

### 2. What is a nano-service?

A nano-service is a lightweight, independently deployable service that extends the `NanoService` abstract base class (`underwrite/services/base.py:93`). Each service:

- Has a unique `service_id` and an Ed25519 `Identity` for signing emitted events.
- Subscribes to typed domain events on a shared `EventBus`.
- Implements `handle(event) -> None` to process incoming events.
- Emits events via `emit(event_type, payload)` which auto-signs.
- Participates in saga orchestration and idempotency.

The 28 services are listed in `SERVICE_NAMES` in `underwrite/config.py:461`.

---

### 3. How do services communicate?

Exclusively through **typed domain events** over the event bus. A service calls `self.emit(event_type, payload)` which creates an `Event` dataclass (`underwrite/events.py:22`), signs it with the service's Ed25519 private key, and publishes it to the bus. Subscribers registered in the `WIRING` dict (`underwrite/handler.py:80`) receive matching events. The bus supports wildcard `"*"` subscriptions. Backends are pluggable: `LocalBus` (in-process, default), SQS, or Modal queues.

---

### 4. How do I add a new service?

1. Create a new sub-package under `underwrite/services/<name>/` with `init.py` and `service.py`.
2. In `service.py`, create a class extending `NanoService` (or `StatefulService`) and implement `handle(self, event)`.
3. Register the service in three places:
   - `SERVICE_MAP` in `underwrite/handler.py:18` — maps name to `module.class`.
   - `SERVICE_CLASSES` in `underwrite/handler.py:49` — maps name to class name.
   - `SERVICE_NAMES` in `underwrite/config.py:461` — adds to the known service list.
4. Add wiring entries in `WIRING` dict to subscribe the service to relevant event types.
5. Configuration: add a `ServiceConfig(enabled=True)` entry under `services` in `underwrite.json`.
6. Run: `underwrite run <name>`.

Plugin discovery is also supported via `importlib.metadata.entry_points` under the `"underwrite.services"` group (`underwrite/plugins.py:34`).

---

### 5. What state store should I use?

| Backend | Class | Use Case |
|---------|-------|----------|
| `memory` | `MemoryStore` | Development, testing, single-process. Data is lost on restart. |
| `filesystem` | `FileStore` | Local development with persistence. Atomic writes with `fsync`. Circuit breaker optional. |
| `postgres` | `PostgresStore` | Production. Connection pooling, circuit breaker, retry policy, migration engine. |

Configured via `store.backend` in `underwrite.json` or `UNDERWRITE_STORE_BACKEND` env var. CQRS is supported via `CQRSStore` — separate read and write stores (`underwrite/store.py:566`). Read replica is configured via `store.read_backend` and `store.read_dsn`.

---

### 6. How does saga orchestration work?

A saga is a distributed transaction with compensating rollbacks. Defined in `underwrite/saga.py`:

1. Define `SagaStep` objects — each has a `forward_event_type`/`forward_payload` and a `compensate_event_type`/`compensate_payload`.
2. Call `orchestrator.start_saga(name, steps)` to create a saga — returns a `saga_id`.
3. Call `orchestrator.execute_all(saga_id)` to execute steps sequentially.
4. If any step fails, all completed steps are rolled back in reverse order via `__rollback()`.
5. Each step is idempotent via store key `saga_step:{saga_id}:{step_index}` — safe replay after crashes.
6. Incomplete sagas can be resumed with `orchestrator.replay_saga(saga_id)`.

The orchestrator registers itself with `NanoService` instances as emitters. Persisted sagas survive restarts.

---

### 7. How are events secured?

Every emitted event carries an Ed25519 signature:

1. The emitting service holds an `Identity` (Ed25519 keypair), created via `Identity.create()` (`underwrite/identity.py:48`).
2. On `emit()`, the payload is serialised and signed: `sign(f"{event_id}:{timestamp}:{event_type}:{payload}")` (`underwrite/services/base.py:266`).
3. The signature and `source_key` (public key) are embedded in the `Event` envelope.
4. On delivery, `AccessControl.assert_verified()` verifies the signature against the trusted key for `event.source` (`underwrite/authz.py:207`).
5. ACL policies control which services may publish/subscribe to which event types.
6. Keys are rotated manually by generating a new `Identity.create(...)` and updating the runtime; rely on `AccessControl.set_replay_window(...)` to keep recent signatures verifiable.

---

### 8. What happens when a service crashes?

The `ServiceSupervisor` (`underwrite/supervisor.py`) tracks handler failures:

- On exception in `NanoService.__handle_event()`, `supervisor.record_failure(service_id)` is called.
- If failures exceed `max_restarts` (default 3), the service is permanently marked unhealthy.
- `Runtime.restart_failing_services()` stops, re-registers, rewires, and restarts the service with exponential backoff.
- Crashed handler events go to the `DeadLetterQueue` for later inspection and replay.
- The circuit breaker on the bus opens for that subscriber after 5 consecutive failures (`CircuitBreaker` in `bus.py:223`), preventing further dispatch until the recovery timeout.

---

### 9. How do I scale the platform?

Underwrite is designed for **local-first, scale-up** (single process). Scaling strategies:

- **Vertical**: Increase worker threads via `bus.max_workers` and `NanoService` `max_concurrent`.
- **Backend swap**: Replace `LocalBus` and `MemoryStore`/`FileStore` with SQS + Postgres for cross-process deployments.
- **CQRS**: Use `CQRSStore` with a read replica to offload query traffic.
- **Service segregation**: Run separate underwrite processes for different service groups (e.g. one for risk/fraud, another for servicing/collections).
- **Plugin services** run in the same process but are independently deployable via `discover_plugins()`.

---

### 10. How does fraud detection work?

The `FraudService` (`underwrite/services/fraud/service.py`) monitors loan origination and repayment events:

- **Wash lending detection** (`__check_wash`): Detects rapid origination→repayment cycles. 3+ consecutive cycles trigger a `WASH_FLAG` event.
- **Velocity/burst detection** (`__check_burst`): Flags borrowers with more than 3 recent originations as `VELOCITY_FLAG`.
- **Large origination**: Originals >$1M trigger a `FRAUD_ALERT`.
- Records are kept per borrower (up to `MAX_BORROWERS=100000`, 1000 events per borrower) and persisted to the store.

---

### 11. What is the delegation graph?

The **delegation graph** (`underwrite/services/mechanism/graph.py`) is the core state machine of the Delegated Underwriting Protocol:

- **Seeds**: Trusted entities with a `base_budget` (e.g. banks, institutional lenders).
- **Users**: Participants sponsored by seeds or other users, with a delegation edge (`sponsor→user`, `amount`).
- Each user has `earned` (repayment credits) and `principal` (outstanding loans).
- **Credit limit** = budget + earned − outgoing delegations.
- **Default propagation**: When a borrower defaults, losses propagate up the delegation chain: borrower's earned → sponsor's earned → sponsor's delegation edge → seed's base budget.
- Queries include path-to-seed, credit-limit, and user listing via `GraphService` (`underwrite/services/graph/service.py`).

---

### 12. How does default propagation work?

When a borrower defaults (`DelegationGraph.default()` at `underwrite/services/mechanism/graph.py:142`):

1. The borrower's earned amount absorbs losses first.
2. Remaining loss propagates to the sponsor: sponsor's earned is reduced, then the delegation edge amount is reduced.
3. This repeats up the chain until the loss reaches a seed, where the seed's `base_budget` absorbs it.
4. If any step cannot absorb the loss, a `ProtocolError` is raised.
5. The borrower's principal is set to 0 and outstanding loans are cleared.

---

### 13. What is the NPA classification system?

The `NPAService` (`underwrite/services/npa/service.py`) tracks non-performing assets per RBI Master Circular guidelines:

| Bucket | Days Past Due |
|--------|--------------|
| Standard | 0–90 days |
| Substandard | 91–180 days |
| Doubtful | 181–360 days |
| Loss | >360 days |

When `DEFAULT_OCCURRED` is received, the service checks if the borrower's overdue days exceed the DLG threshold (`__trigger_days`, default 120). If so, it emits `DLG_TRIGGERED` and marks the account with `dlg_invoked = True`. The `classify_overdue_days()` static method maps days to buckets. The `mark_overdue()` method allows external updates to days-past-due counters.

---

### 14. How do I monitor the system?

Multiple observability mechanisms built-in:

- **Health checks**: `HealthRegistry` aggregates per-subsystem checks (bus, store, services, saga, tracer, DLQ, supervisor). Accessible via `underwrite health` CLI or `/v1/health` HTTP endpoint.
- **Metrics**: `MetricsCollector` tracks counters, timers, and gauges. Snapshots via `underwrite metrics` CLI, Prometheus export at `/v1/metrics`, or OTLP export via `config.tracing.exporter = "otlp"`.
- **Tracing**: `Tracer` with console or OTLP span export. Each event carries `trace_id` and `parent_span_id` for distributed tracing correlation.
- **Structured logging**: JSON log format configurable via `UNDERWRITE_LOG_FORMAT=json`. PII fields auto-redacted. Correlation IDs attached to log records.
- **Dead-letter queue**: Inspect and replay failed events with `underwrite dlq`.

---

### 15. How do I debug a failed event?

1. Check if the event is in the dead-letter queue:
   ```
   underwrite dlq
   ```
2. Inspect the error message for each failed entry.
3. Check the runtime logs for exception tracebacks (look for `handler {service} failed processing {event_type}`).
4. Check circuit breaker state — if open, the subscriber is not receiving events.
5. Check idempotency — if the event is a duplicate, it is silently dropped (logged at DEBUG level).
6. For signature failures, check `AuthzError` logs indicating invalid signatures.
7. Replay after fixing the issue:
   ```
   underwrite dlq --replay
   ```

The `Event` envelope carries `correlation_id`, `trace_id`, and `parent_span_id` for cross-service trace correlation.

---

### 16. What configuration options are available?

The full configuration schema is in `underwrite/config.py`. Key sections:

| Section | Key Settings | Env Var Prefix |
|---------|-------------|----------------|
| `bus` | `backend`, `rate_limit`, `max_workers`, `max_futures` | `UNDERWRITE_BUS_*` |
| `store` | `backend`, `dsn`, `pool_size`, `read_backend`, `read_dsn` | `UNDERWRITE_STORE_*` |
| `logging` | `level`, `output`, `format` | `UNDERWRITE_LOG_*` |
| `identity` | `private_key`, `public_key`, `key_ttl`, `key_grace` | `UNDERWRITE_IDENTITY_*` |
| `tracing` | `enabled`, `exporter` | `UNDERWRITE_TRACING_*` |
| `saga` | `enabled` | `UNDERWRITE_SAGA_ENABLED` |
| `secrets` | `backend`, `url`, `token`, `region` | `UNDERWRITE_SECRETS_*` |
| `recovery` | `auto_restart`, `max_restarts`, `backoff_seconds` | `UNDERWRITE_RECOVERY_*` |
| `audit` | `max_ledger`, `export_url` | `UNDERWRITE_AUDIT_*` |
| `fee` | `schedules` (late_payment, origination, prepayment, service) | — |
| `governance` | `param_ranges`, `param_defaults` | — |

Config is loaded from a JSON file, then overlaid with `UNDERWRITE_*` environment variables.

---

### 17. How do I migrate the database?

Migrations are defined in `underwrite/migrate.py` using the `MigrationPlan` and `Migration` classes:

1. Add a new `Migration` to `default_plan()` with an incrementing version number and SQL statements.
2. If `migration.auto_migrate` is `true` (default), migrations run automatically at `Runtime.start()`.
3. Or run manually: `underwrite migrate`.
4. Applied versions are tracked in the `migrations` table (`version INT, description TEXT, applied_at TIMESTAMPTZ`).
5. To roll back: `DELETE FROM migrations WHERE version = N;` and manually revert the schema.

---

### 18. How do I contribute?

The project uses standard Python tooling:

```bash
pip install -e ".[dev,risk,postgres]"
make test        # Runs pytest with coverage
make lint        # Runs ruff
make typecheck   # Runs mypy
```

- Ruff linter config: `[tool.ruff.lint] select = ["E", "F", "I", "UP", "B"]`, line length 120.
- mypy config: `ignore_missing_imports = true`.
- Pre-commit hooks are configured in `.pre-commit-config.yaml`.
- Mutation testing via `mutmut` (optional: `pip install underwrite[mutation]`).
- Tox for multi-env testing (`tox.ini`).
- See `CONTRIBUTING.md` for full details.

---

### 19. What are the system requirements?

- **Python**: 3.10, 3.11, 3.12, or 3.13 (declared in `pyproject.toml` `requires-python = ">=3.10"`).
- **OS**: Linux, macOS, or Windows (pure Python, no platform-specific dependencies).
- **Optional**: PostgreSQL (for `PostgresStore`), Docker (for `testcontainers` in integration tests).
- **No external message broker required** — `LocalBus` is fully in-process.

---

### 20. Is there a roadmap?

The project is in **Beta** (`Development Status :: 4 - Beta`). The TODO (`TODO.md`) and CHANGELOG (`CHANGELOG.md`) document planned and completed work. Key areas of ongoing development:

- SQS and Modal bus backends for distributed deployment.
- Enhanced fraud detection models and ML risk scoring integration.
- Governance parameter evolution via on-chain proposals.
- Collateral liquidation and settlement workflows.
- Recovery and collections automation.
- Additional state store backends.
- Enhanced OTLP/metrics observability.
