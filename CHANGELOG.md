# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
