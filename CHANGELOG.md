# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.1] — 2026-05-29

### Added

- **setuptools-scm** — version is now derived from git tags via `setuptools-scm`, eliminating the version drift between pyproject.toml, CHANGELOG, and git tags.
- **Concurrency tests** — thread-safety tests for `MechanismService`, `KeyRotationManager`, and `LocalBus` under concurrent event dispatch.
- **Security CI** — `bandit` and `pip-audit` integrated into CI pipeline.
- **Batch persistence** — `AuditService` and `FraudService` now use counter-based batching to avoid O(n) serialization on every event.
- **Async rate limiter lock** — `asyncio.Lock` protects the token-bucket state in FastAPI middleware, fixing a data race under concurrent requests.
- **Docker setup** — `Dockerfile` and `docker-compose.yml` for development and production deployments.
- **Plugin system** — services can now be registered via `importlib.metadata.entry_points` under the `"underwrite.services"` group.
- **Event schema registry** — `SchemaRegistry` validates event payloads at publish time and supports versioned schemas.
- **Async-native event bus** — `AsyncNativeBus` implementation using `asyncio.Queue` for truly non-blocking async dispatch.
- **Mutation testing** — `mutmut` configuration and CI job to measure test suite effectiveness.
- **OpenAPI documentation** — FastAPI app now includes descriptions, examples, and response models for all endpoints.
- **Fine-grained locking in MechanismService** — split state lock from I/O lock to reduce contention during persistence.

### Fixed

- **Rate limiter data race** — `__serve__.py` token-bucket state is now protected by `asyncio.Lock`, preventing 429 errors under concurrent requests.
- **Version drift** — pyproject.toml `version` field replaced with `dynamic = ["version"]` driven by `setuptools-scm`.
- **Secrets test failures** — fixed 6 failing tests in `test_secrets_faults.py` caused by mock exception hierarchy issues.
- **Mypy errors** — resolved 16 type errors across `__runtime__.py` and `__init__.py`.
- **Ruff E501** — fixed line-length violation in `collateral/service.py`.

### Changed

- **AuditService persistence** — now syncs to store every 10 events instead of every event, reducing serialization overhead by ~10x.
- **FraudService persistence** — now syncs to store every 10 events instead of every event.
- **`__config__.py`** — configuration schema validation migrated from hand-rolled recursive validator to Pydantic models, reducing module size by 300+ lines.
- **MechanismService locking** — state mutations use `threading.Lock` for fast operations; I/O operations use a separate lock to avoid blocking the event loop.

## [0.2.0] — 2026-05-26

### Added

- **Async event bus** — `AsyncEventBus` ABC and `AsyncLocalBus` implementation for non-blocking event dispatch. (`__bus__.py`)
- **Configurable max futures** — `BusConfig.max_futures` controls pending future cap (default 10000). (`__config__.py`, `__bus__.py`)
- **FraudService borrower cap** — `MAX_BORROWERS = 100000` prevents unbounded dict growth; oldest borrower evicted via `OrderedDict`. (`services/fraud/service.py`)
- **NaN/Inf guard in RiskModel** — inputs validated with `math.isfinite` before prediction. (`services/risk/model.py`)
- **Runtime.async_publish()** — async-compatible publish for use in FastAPI endpoints without blocking. (`__runtime__.py`)
- **HTTP `/publish` endpoint** — POST endpoint in FastAPI for external event publishing. (`__serve__.py`)
- **`__all__` in `__events__.py`, `validate.py`, `__exceptions__.py`, `prometheus_export.py`** — missing module exports. (`__events__.py`, `validate.py`, `__exceptions__.py`, `prometheus_export.py`)
- **DLQ CLI `--replay` command** — replay dead-letter events from the CLI. (`__cli__.py`)

### Changed

- **`__build_authz()` narrowed exception handling** — `except Exception` replaced with specific `(json.JSONDecodeError, OSError)`. (`__runtime__.py`)
- **`break_even` catastrophic cancellation** — `clamped_dp` now bounded above by `1.0 - EPSILON` so `1.0 - clamped_dp ≥ EPSILON`. (`services/mechanism/service.py`)
- **Metrics eviction** — evicts excess entries rather than trimming to `max_metrics // 3` per type in a while loop; reduces total pops to exactly `excess`. (`__metrics__.py`)
- **Audit `save_jsonl` streaming** — writes chunks of 1000 records at a time instead of building one giant string. (`services/audit/service.py`)
- **FeeService PAYMENT_OVERDUE** — added missing loan_id warning log. (`services/fee/service.py`)
- **`.env.example`** — added `UNDERWRITE_BUS_MAX_FUTURES` var. (`.env.example`)

### Fixed

- **Path traversal in FileStore** — additional `relative_to()` check ensures resolved path stays under data directory. (`__store__.py`) — already partially fixed in v0.1.0.

## [0.1.0] — 2026-05-22

### Added

- **Event signature covers payload** — the signed message now includes `json.dumps(payload, sort_keys=True)`. Tampered payloads are detected on verification. Breaking change to signature format (all existing signatures invalidated). (`__authz__.py`, `services/base.py`)
- **Model integrity verification** — `RiskModel` computes SHA-256 of model file before loading, verified against `RISK_MODEL_SHA256` env var or `.sha256` sidecar. (`services/risk/model.py`)
- **Thread safety on MechanismService** — all state mutations (10 dicts/sets) protected by `threading.RLock`. Properties, `credit_limit`, `__sync_store`, `__load_store` all under lock. (`services/mechanism/service.py`)
- **Thread safety on KeyRotationManager** — all 3 public methods (`get_or_create`, `rotate`, `verify_with_rotation`) under `threading.RLock`. (`__identity__.py`)
- **Saga TOCTOU fix** — `execute_step` holds `RLock` across the full emit window; rollback re-enters safely. (`__saga__.py`)
- **Fee input validation** — `float()` replaced with `get_finite()` to reject `inf`/`nan` amounts. (`services/fee/service.py`)
- **Private key excluded from config serialization** — `Configuration.to_dict()` no longer dumps `private_key` to plaintext JSON. (`__config__.py`)
- **DeadLetterQueue cap** — max 10,000 records; oldest evicted on overflow. (`__bus__.py`)
- **Audit ledger cap** — `deque(maxlen=100000)` bounds the in-memory audit log. (`services/audit/service.py`)
- **Store operation timeouts** — FileStore uses `ThreadPoolExecutor` per I/O call; PostgresStore sets `statement_timeout`. (`__store__.py`)
- **Path traversal protection** — `FileStore.__path()` rejects `..` and absolute-key paths. (`__store__.py`)
- **Service registry extraction** — `SERVICE_MAP`, `SERVICE_CLASSES`, `WIRING` moved to `_service_registry.py` (reduced `__runtime__.py` by 112 lines). (`_service_registry.py`)
- **Typing hygiene** — PEP 585/604 generics, `_Connection` Protocol, `_Emitter` Protocol, `__all__` on 12 modules, `py.typed` marker, bare set→`set[str]` in bus, bare tuple→`tuple[type[Exception],...]` in circuit, typed `Store.migrate(plan: MigrationPlan)`. All ruff rules clean (E, F, I, UP, B).
- **`Makefile`** — install/dev/test/lint/typecheck/clean targets.
- **`py.typed`** — PEP 561 compliance marker.
- **`from __future__ import annotations`** — in all source files (not all test files).
- **`requirements.lock` and `requirements-dev.lock`** — pinned transitive deps for reproducible builds. _(Removed in v0.1.0 — pyproject.toml is now the single source of truth.)_
- **509 tests** — 0 failures, 0 warnings. Ruff: clean. Mypy: 116 pre-existing errors in 25 files.

### Changed

- **Circuit breaker traceback preservation** — `raise` not `raise exc` in RetryPolicy; `from e` in validation helpers.
- **Pickle→joblib as primary model loader** — `joblib.load()` preferred; `pickle` is fallback if joblib absent.
- **DLQ stores `traceback.format_exc()`** instead of `str(exc)`.
- **Store `logger.error`→`logger.exception`** for traceback preservation.
- **Bus executor shutdown** — wrapped in try/except `TimeoutError` with warning.

### Removed

- Redundant `requirements.lock` and `requirements-dev.lock` — all dependencies managed in `pyproject.toml`.
- Unused imports (68 F401 violations fixed).
- Dead variables (`trace_id`, `parent_span_id` in `services/base.py`).

### Security

- **CRITICAL: Event signature now covers payload** — previously only `event_id:timestamp:event_type` was signed. Payload modifications went undetected. All existing signatures are invalidated; keys must be rotated.
- **CRITICAL: Thread safety on MechanismService** — all protocol state (seeds, balances, delegation graph) was previously unprotected under concurrent event dispatch.
- Model files are integrity-checked before loading.
- Private keys excluded from config serialization.
- Path traversal blocked in FileStore.

## [0.0.0] — 2026-05-18

### Added

- Initial codebase: event bus, store backends, nano-service ABC, CLI, configuration engine.
- 28 nano-service implementations across lending underwriting domain.
- Ed25519 cryptographic identity and event signing.
- Saga orchestrator with forward/reverse step execution.
- Circuit breaker with configurable retry policy.
- Health check registry and metrics collector.
- Distributed tracing with span lifecycles.
- Access control with policy evaluation and signature verification.
- Dead-letter queue for failed event processing.
- Idempotency guard for duplicate event detection.
- CQRS read/write store separation.
- Full test suite (474 tests).

[0.3.1]: https://github.com/sachn-cs/unsecured-lending-underwriting/compare/v0.2.0...v0.3.1
[0.2.0]: https://github.com/sachn-cs/unsecured-lending-underwriting/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sachn-cs/unsecured-lending-underwriting/compare/v0.0.0...v0.1.0
[0.0.0]: https://github.com/sachn-cs/unsecured-lending-underwriting/releases/tag/v0.0.0
