# Production-Readiness Review: `underwrite`

## 1. Overall Readiness Verdict

**Conditionally ready** — the architecture and testing discipline are strong, but 3 critical defects (signature gap, unsafe deserialization, lock-free state machine) and 5 high-severity issues must be resolved before production.

---

## 2. Executive Summary

**Strengths:**
- Clean nano-service architecture with well-defined ABCs (`EventBus`, `Store`, `NanoService`)
- 509 passing tests, 0 failures, ruff fully clean
- `py.typed` marker, PEP 585 generics, `__all__` on all infra modules
- Google-style naming conventions consistently applied
- Circuit breaker, retry policy, dead-letter queue, idempotency guard — good operational patterns
- Lockfiles for reproducible builds

**Critical weaknesses:**
1. **Event signature does not cover payload** — payload integrity is unprotected. An attacker can modify `event.payload` without invalidating the signature.
2. **Pickle/joblib model loading** — arbitrary code execution if the model file is compromised (env-var path, no integrity check).
3. **MechanismService has zero locks** — all protocol state (`__seeds`, `__earned`, `__parent`, etc.) is mutated without synchronization. Concurrent event dispatch via `ThreadPoolExecutor` causes data races.

**High-severity issues:**
4. Private key exposed via name mangling and written to plaintext JSON config
5. `KeyRotationManager` has no locks — concurrent rotation loses keys
6. Saga TOCTOU — forward action can execute after compensation starts
7. `__sync_store()` reads state without lock — inconsistent snapshot

**Architecture:** Strong overall (ABCs, CQRS, saga pattern, event-driven). The MechanismService is the weakest link — 354 lines, no concurrency protection, 14 private methods, 3 hardcoded constants.

**Testing:** 509 tests, good coverage. Gaps: no concurrency/stress tests, no negative tests for signature verification, no model integrity tests.

---

## 3. Prioritized Findings

### CRITICAL

| # | Finding | Category | File(s) | Evidence | Impact |
|---|---------|----------|---------|----------|--------|
| C1 | **Event signature excludes payload** | Security | `__authz__.py:102`, `services/base.py:110` | `to_verify = f"{event.event_id}:{event.timestamp}:{event.event_type}"` — no payload | Any signed event's payload can be modified without invalidating the signature. All services relying on `assert_verified()` are vulnerable. |
| C2 | **Pickle/joblib deserialization** | Security | `services/risk/model.py:24,31` | `joblib.load(model_path)` / `pickle.load(fh)` with no integrity check | Arbitrary code execution if model file is compromised. Model path from env var `RISK_MODEL_PATH`. |
| C3 | **Lock-free state machine** | Concurrency | `services/mechanism/service.py` (all handlers) | `__add_seed`, `__add_user`, `__repay`, `__originate`, `__default`, `__revoke` all modify `__seeds`, `__earned`, `__parent`, `__children`, `__delegation`, `__base_budget`, `__principal`, `__loans` without any lock. Bus dispatch uses `ThreadPoolExecutor`. | Data races on all protocol state. Corrupted balances, inconsistent delegation graph, diverged in-memory/persisted state. |

### HIGH

| # | Finding | Category | File(s) | Evidence | Impact |
|---|---------|----------|---------|----------|--------|
| H1 | **Private key exposed** | Security | `__identity__.py:47`, `__config__.py:188` | `__private_key: str = ""` — name-mangled to `_Identity__private_key`, readable by any code with reference. `Configuration.to_dict()` serializes it to plaintext JSON. | Any code with a reference to `Identity` can read the private key. Config JSON on disk exposes key material. |
| H2 | **KeyRotationManager lock-free** | Concurrency | `__identity__.py:162-187` | `get_or_create()`, `rotate()`, `verify_with_rotation()` access `self.__current` and `self.__previous` without any lock | Concurrent `rotate()` calls lose keys. Concurrent `get_or_create()` can return different `Identity` objects for the same `service_id`. |
| H3 | **Saga TOCTOU** | Concurrency | `__saga__.py:78-100` | `execute_step()` acquires lock only for status check, releases, then calls `emitter.emit()` (forward action). Between release and re-acquire, `__rollback()` can set `status="compensating"`. | Forward action executes on a saga that is already compensating. The `completed_steps.append()` at re-acquire adds the step AFTER rollback's snapshot, so it is never compensated. |
| H4 | **Inconsistent store snapshot** | Reliability | `services/mechanism/service.py:331-354` | `__sync_store()` reads all state dicts (`__seeds`, `__earned`, etc.) without a lock, then writes to store. Concurrent handler mutations between reads produce an inconsistent snapshot. | On restart, `__load_store()` restores an inconsistent state (e.g., `__earned` totals that don't match `__principal`). |
| H5 | **Model failure silent degradation** | Reliability | `services/risk/model.py:36-41` | `except Exception as exc:` catches ALL model failures and falls through to heuristic. The caller (`RiskService.handle`) never knows the model failed. | Production system silently serves heuristic scores when model is down. Compliance/audit unaware. |

### MEDIUM

| # | Finding | Category | File(s) | Evidence | Impact |
|---|---------|----------|---------|----------|--------|
| M1 | **SQL injection via table name** | Security | `__store__.py` lines 311–338 | `f"SELECT value FROM {self.__table} WHERE key = %s"` — table name interpolated, not parameterized | SQL injection if `self.__table` is attacker-controlled. Currently hardcoded to `"store"`, but risk if config-driven in future. |
| M2 | **No depth limit on delegation chain** | Reliability | `services/mechanism/service.py:108-114` | `__required_delegation` recursively traverses parent chain with no max-depth guard | Deeply nested delegation (~1000+ levels) can overflow the call stack. Production DoS via user-registration chain. |
| M3 | **Catastrophic cancellation in break_even** | Reliability | `services/mechanism/service.py:293` | `1.0 - clamped_dp` when `dp ≈ 0.999999999999` loses nearly all precision | Protocol premium calculation can be wildly inaccurate for near-1 default probabilities. |
| M4 | **Fraud records unbounded growth** | Operations | `services/fraud/service.py:18,41` | `self.__records` is a plain dict, appends on every `LOAN_ORIGINATED` and `REPAID` | Memory leak — records grow indefinitely over the service lifetime. |
| M5 | **FileStore executor never shut down** | Operations | `__store__.py:147-149` | `ThreadPoolExecutor(max_workers=1)` created but never `.shutdown()` | Leaks one thread per FileStore instance over the process lifetime. |
| M6 | **Fee service bypasses `float()` validation** | Reliability | `services/fee/service.py:34` | `float(event.payload.get("principal", 0))` — raw `float()` instead of `get_finite()` validator | `float("inf")` or `float("nan")` produces infinite/NaN amounts, corrupting downstream calculations. |

### LOW

| # | Finding | Category | File(s) | Evidence | Impact |
|---|---------|----------|---------|----------|--------|
| L1 | **SSN regex requires dashes** | Security | `__pii.py:38` | Pattern `\b\d{3}-\d{2}-\d{4}\b` — undashed `123456789` not detected | PII leak for SSns without dashes. |
| L2 | **Config `init` path not sanitized** | Security | `__cli__.py:48` | `Path(path).exists()` — user-supplied path used directly | Local symlink overwrite if path points to sensitive file. |
| L3 | **FileStore `keys()` no pagination** | Operations | `__store__.py:215` | `rglob("*.json")` — enumerates all files with no limit | Unbounded enumeration DoS for large data directories. |
| L4 | **Governance silently ignores proposals** | Operations | `services/governance/service.py:40-44` | `if param not in self.__params: return` — no log, no event | Administrator sends proposal with typo, gets zero feedback. |
| L5 | **Fee silently ignores unknown types** | Operations | `services/fee/service.py:30-31` | `if not loan_id or fee_type not in FEE_SCHEDULES: return` — no warning | Configuration mistake (`fee_type` typo) goes undetected. |
| L6 | **Saga silent returns False** | Operations | `__saga__.py:82,84,88,106,119,125` | All `return False` / `return` on not-found emit no log | Debugging saga failures requires tracing through opaque booleans. |

---

## 4. Dead Code Inventory

### Confirmed Dead Code

| Item | File | Evidence | Deletion Safe? |
|------|------|----------|----------------|
| `trace_id = ""` | `services/base.py:103` | Assigned but never read | Yes — removed in P3 |
| `parent_span_id = ""` | `services/base.py:104` | Assigned but never read | Yes — removed in P3 |

### Suspected Dead Code

| Item | File | Evidence | Assessment |
|------|------|----------|------------|
| `HAS_CRYPTO` import in test | `tests/test_cli_faults.py:25` | Imported but never used | Already addressed in P3. Safe to remove. |
| `cause = exc.__cause__` in test | `tests/test_risk_faults.py:112` | Assigned but never read | Already addressed in P3. |

### No dead modules, orphaned files, or dead CLI commands detected

All 28 services are registered in `SERVICE_MAP` and `SERVICE_CLASSES`. All CLI commands (`init`, `run`, `list`, `identity`, `health`, `dlq`, `metrics`, `migrate`) are registered in the typer app and called from `main()`. The `validate.py` module's 10 functions are all imported/used across service implementations.

---

## 5. Modularity and Architecture Assessment

### Strong Boundaries
- **Store ABC** (`__store__.py`) — clean abstraction with 5 concrete implementations. CQRS wrapper (`CQRSStore`) follows decorator pattern cleanly.
- **EventBus ABC** (`__bus__.py`) — clean pub-sub interface with one concrete implementation (`LocalBus`). Easily swappable for SQS/Modal.
- **NanoService ABC** (`services/base.py`) — clean lifecycle (subscribe/start/stop/handle) with cross-cutting concerns (authz, tracing, metrics, saga) injected, not inherited.
- **Configuration** (`__config__.py`) — single module managing all config, 10 sub-config dataclasses. Clean separation from runtime logic.

### Weak Boundaries
- **Runtime** (`__runtime__.py`) — was 407 lines, now 293 after registry extraction. Still handles: service registry, lifecycle, health registration, tracer/build bus, store building, authz building, migration orchestration, logging config. Violates single-responsibility. The `__build_*` methods (tracer, bus, store, read_store, authz) are factory methods that should live in dedicated factory modules.
- **MechanismService** (`services/mechanism/service.py:354` lines) — largest service by 5×. Mixes protocol state machine, delegation graph traversal, financial calculations, and persistence. Should be split into domain+persistence layers.

### Coupling Risks
- **Circular import risk** — `__saga__.py` and `services/base.py` have mutual imports (saga imports `Event` from `__events__`, base imports `SagaOrchestrator` from `__saga__`). The `_Emitter` Protocol avoids the circular dependency at the annotation level.
- **`RiskService` → `RiskModel`** — tight coupling via hardcoded `joblib.load()` / `pickle.load()`. Model is instantiated in `RiskService.__init__` (`services/risk/service.py:36-41`). No strategy pattern for model loading.
- **`FeeService` → `FEE_SCHEDULES`** — hardcoded dict in module. Not configurable. Changing fee rates requires a code deploy.
- **`GovernanceService` → `PARAM_RANGES`** — hardcoded dict. Same issue.

### No Circular Dependencies Detected
All imports flow in one direction: `services/*` → `underwrite.*` → standard library.

---

## 6. Encapsulation and Cohesion Assessment

### Implementation-Detail Leakage
- **`__identity__.py:47`** — `__private_key` is a dataclass field. `dataclasses.asdict()` or `vars()` exposes it.
- **`__config__.py:188-189`** — `to_dict()` serializes `private_key` and `dsn`. These should be excluded from dict serialization (`field(exclude=True)` or similar).
- **Tests accessing `__private` attributes** — `test_integration.py` accesses `_Runtime__bus`, `_Runtime__store`; `test_risk_faults.py` accesses `_RiskService__model`, `_AuditService__ledger`. Tests should use public APIs or add test-only properties.

### Overgrown Modules/Classes
- **`MechanismService`** (354 lines, 14 private methods) — largest class by far. Handles: state machine (add/repay/default/revoke), delegation graph (path_to_seed, required_delegation), financial calculations (credit_limit, break_even, protocol_premium), and persistence (load_store, sync_store).
- **`__runtime__.py`** (293 lines) — now smaller but still handles factory building, lifecycle, health registration, migration, and config application.
- **`__store__.py`** (347 lines) — 5 classes, 2 inline imports, mix of ABCs and concrete implementations. The inline imports (`from underwrite.__exceptions__ import ...`) are a code smell from class ordering constraints.

### Mixed Responsibilities
- **`__cli__.py`** (209 lines) — CLI commands (value objects) mixed with initialization logic (`_load_config`, config path handling). The `init` command writes config; the `identity` command creates `Identity` objects.
- **`services/base.py:98-132`** — `emit()` method mixes: event creation, signing, authz, publishing, metrics. Could be decomposed into event factory + signer + publisher.

---

## 7. Reliability and Correctness Assessment

### Algorithm Correctness Risks
- **Catastrophic cancellation in `break_even`** (`mechanism/service.py:293`): `1.0 - clamped_dp` when `dp ≈ 0.999999999999` loses precision. Fix: use `math.fma` or restructure to avoid subtraction of near-equal values.
- **Float overflow in `pr * principal * term`** (`mechanism/service.py:191,294`): Triple float multiplication can overflow to `inf` even though each input is individually finite. Fix: clamp intermediate product or use `math.prod` with overflow detection.
- **Wash detection skips non-alternating patterns** (`fraud/service.py:51-57`): `i += 2` assumes strict `(origination, repayment)` alternation. Sophisticated adversary interspersing events evades detection.

### Edge-Case Failures
- **NaN propagation** (`risk/model.py:48-49`): `principal / 1_000_000.0` with `principal=nan` produces `nan`, then `min(max(nan, 0.01), 0.5)` returns `nan`. Fix: add `math.isfinite` check before return.
- **Term division by zero prevented** (`risk/model.py:45`): `max(term, 1.0)` — correct.
- **Empty steps saga** (`__saga__.py:72`): `start_saga` with empty `steps` immediately "completes". Should validate non-empty.

### Input Validation Gaps
- **FeeService uses `float()` instead of `get_finite()`** — allows `inf`/`nan` amounts.
- **`validate.py` assumes `payload` is a dict** — no guard in any of the 10 functions.
- **`RiskModel.predict()`** — no validation of `principal`/`term` inputs.
- **`SagaOrchestrator.start_saga()`** — no validation that `steps` is non-empty or `name` is non-empty.

---

## 8. Resilience Assessment

### Failure-Handling Gaps
- **Model failure → silent degradation** (`risk/model.py:36-41`): Caller gets a score but doesn't know it's a heuristic. Fix: emit a warning event or return degraded status.
- **Governance unknown params** (`governance/service.py:40-44`): Silent discard. Fix: `logger.warning`.
- **Fee unknown fee types** (`fee/service.py:30-31`): Silent discard. Fix: `logger.warning`.
- **Saga not-found** (`__saga__.py:82,84,88,106,119,125`): Silent `False`. Fix: `logger.warning`.

### Observability Weaknesses
- **Google-style docstrings only on 3 out of 123 files** — `__identity__.py:Identity.create`, `__runtime__.py:Runtime.start`, `__store__.py:FileStore`. All other modules/classes/methods lack structured Args/Returns/Raises documentation.
- **No structured logging** — all logging uses `logging` module with string formatting. No correlation IDs in log lines (correlation_id is on events but not propagated to log context).
- **No health check for fraction of services registered** — health checks are registered for bus, store, services, metrics, tracer, saga, dlq. But individual service health is only available via `Runtime.health` → `services` → `running` list. Per-service detailed health is not exposed.

### Recovery Limitations
- **No saga recovery after Runtime restart** — saga state is in-memory only. After crash, all in-flight sagas are lost. No persisted saga log.
- **No event replay from DLQ on startup** — dead letters are persisted in memory, lost on process restart.
- **No store transaction support** — `FileStore` and `PostgresStore` have no atomic multi-key operations. Partial failures leave inconsistent state (the mechanism service's `__sync_store` writes multiple keys non-atomically).

---

## 9. Async and Concurrency Assessment

### Confirmed Race Conditions

| # | Location | Issue | Severity |
|---|----------|-------|----------|
| 1 | `services/mechanism/service.py` (all state mutations) | Zero locks on all protocol state dictionaries. Bus uses `ThreadPoolExecutor` for concurrent dispatch. | **Critical** |
| 2 | `__saga__.py:78-100` | TOCTOU: forward action fires after compensation starts. Step added to `completed_steps` after rollback snapshot. | **High** |
| 3 | `__identity__.py:162-187` | `KeyRotationManager` has no locks. Concurrent `rotate()` loses keys. | **High** |
| 4 | `services/mechanism/service.py:331-354` | `__sync_store()` reads state without lock → inconsistent snapshot. | **High** |
| 5 | `services/fraud/service.py:41` | `setdefault`+`append` is non-atomic. Two concurrent handlers for same borrower race. | **Medium** |
| 6 | `services/mechanism/service.py:116-128` | `__path_to_seed()` traverses parent chain without lock → `KeyError` on concurrent mutation. | **Medium** |
| 7 | `services/mechanism/service.py:89-100` | `credit_limit()` reads multiple state dicts without lock → torn read. | **Medium** |

### Thread-Safe Components (verified)
- `MemoryStore` — all operations under `self.__lock`
- `FileStore` — `set`/`delete` under lock, `get` filesystem I/O is safe
- `PostgresStore` — pool access under lock, `try/finally` release pattern
- `LocalBus` — handler lists under lock, future tracking under lock
- `MetricsCollector` — all operations under lock
- `HealthRegistry` — snapshot under lock
- `DecisionService` — signal pop under lock

### No async/await Usage
The codebase is entirely synchronous. `LocalBus` uses `concurrent.futures.ThreadPoolExecutor` for concurrent dispatch. There is no `asyncio` code path. This is consistent with the in-process design but prevents integration with async frameworks (FastAPI, etc.) without explicit wrapper layers.

---

## 10. Testing and Verification Assessment

### Strengths
- 509 tests, 0 failures, 0 warnings
- `hypothesis` used for property-based testing (in `test_store.py`, `test_pii.py`)
- All service implementations have dedicated test files
- Framework integration tests cover bus + store + runtime end-to-end
- Fault injection tests (17 files with "faults" in the name) cover error paths

### Gaps
| Gap | Severity | Details |
|-----|----------|---------|
| **No concurrency/stress tests** | **High** | No tests verify thread safety of any component. The race conditions in MechanismService, KeyRotationManager, and SagaOrchestrator are undetected. |
| **No negative tests for signature verification** | Medium | No test verifies that signature verification rejects tampered payloads (which is particularly important since payload is not in the signed message). |
| **No model integrity tests** | Medium | No test verifies `RiskModel` rejects bad model files (corrupted pickle, wrong object type) or handles NaN/inf inputs. |
| **Private attribute access in tests** | Medium | `test_integration.py` accesses `_Runtime__bus`, `_Runtime__store`. `test_risk_faults.py` accesses `_RiskService__model`, `_AuditService__ledger`. Brittle — breaks if implementation details change. |
| **No saga persistence tests** | Low | No test verifies saga behavior across restart (currently impossible since saga is in-memory, but this is an architectural gap). |
| **No DLQ persistence tests** | Low | DLQ is in-memory only. No test verifies dead letter behavior across restarts. |

### Flaky/Brittle Tests
- `test_health.py:53-58` — `test_check_unregistered_during_status_skipped`: Registers a check, calls `status()`, asserts the check is present. This test races with the lock-free status impact of concurrent register/unregister. Currently passes because nothing else runs concurrently, but fragile.
- `test_saga.py` — test emitter classes (`FakeEmitter`, etc.) don't implement the `_Emitter` protocol correctly (return `None` instead of `Event`). These are mypy errors, not runtime errors, but they indicate the test mocks are inaccurate.

---

## 11. Performance and Scalability Assessment

### Identified Hotspots

| Issue | Location | Impact | Recommendation |
|-------|----------|--------|----------------|
| **Unbounded fraud records** | `fraud/service.py:18` | Memory grows linearly with event count — O(n) memory leak | Add `deque(maxlen=N)` or TTL-based eviction |
| **Unbounded saga error strings** | `__saga__.py:54,142` | `saga.error` is a plain string that grows with concatenation | Cap error length or use list |
| **`FileStore.keys()` rglob** | `__store__.py:215` | Enumerates all files — O(n) I/O with no limit on n | Add pagination or limit param |
| **Thread-per-FileStore executor** | `__store__.py:147-149` | One thread per instance, never shut down | `shutdown()` or use shared executor |
| **`__path_to_seed()` O(depth)** | `mechanism/service.py:116-128` | Each call traverses entire delegation chain to root. Called in `required_delegation` which is recursive. | Cache parent→seed mappings, add depth limit |
| **`__required_delegation` recursion** | `mechanism/service.py:108-114` | Recursive with no depth limit. Deep chain = stack overflow. | Convert to iterative with depth limit |

### I/O Bottlenecks
- **`__sync_store()` writes all state on every event** (`mechanism/service.py:331-354`): Writes 7+ store keys per event. Each write is a separate JSON file write (FileStore) or SQL INSERT (PostgresStore). This serializes the event loop on I/O.
- **`FileStore.keys()` scans all files** — could be slow for large data directories.
- **`AuditService.save_jsonl()` builds full string in memory** — writes entire ledger as a single string. Large ledgers cause OOM.

### Optimization Opportunities
- **Caching in `credit_limit()`** — the delegation chain traversal is repeated for every quote/origination. Cache TTL-based results.
- **Batch store writes** — `__sync_store()` could batch all key writes into a single operation (especially for PostgresStore with transaction support).
- **AuditService uses `deque(maxlen=100000)`** — already capped from P2. Good.

---

## 12. Dependency and Packaging Assessment

### Strengths
- `pyproject.toml`-only build (PEP 621) — modern, clean
- `requirements.lock` + `requirements-dev.lock` — pinned transitive deps for reproducible builds
- `py.typed` marker (PEP 561)
- Minimal core dependencies: `cryptography`, `typer`, `joblib` (joblib is transitive via sklearn, but pinned explicitly)
- Ruff 0.15.10, mypy 1.20.1, pytest 9.0.2 — modern tooling

### Issues

| Issue | Severity | Details |
|-------|----------|---------|
| `joblib` in core deps but only used by `risk` extra | Low | `joblib` is listed in `requirements.lock` as a core dep but only used by `services/risk/model.py`. Should be moved to `risk` extra. |
| `psycopg2-binary` in `postgres` extra but not in `requirements-dev.lock` | Low | Listed as comment `# psycopg2-binary>=2.9 (install separately when needed)` instead of pinned in lockfile. |
| No `setup.py` or `setup.cfg` | None | pyproject.toml is sufficient for PEP 621. |
| `ulu` installed as editable (`ulu==0.2.0`) | Info | Package name from `pyproject.toml` is `underwrite` but `pip list` shows `ulu 0.2.0`. The `[project]` name field in pyproject.toml should be `underwrite`, not `ulu`. This discrepancy means `pip install underwrite` won't find this package. |

---

## 13. Final Recommendation

### Minimum Required Changes Before Production

1. **Fix event signature to include payload** (`__authz__.py:102`, `services/base.py:110`) — **Critical**. Add `event.payload` to the signed message string. This changes the signature format and requires key rotation, but payload integrity is a hard requirement for a lending platform.

2. **Add locks to MechanismService** (`services/mechanism/service.py`) — **Critical**. Add a single `threading.Lock` acquired by all handler methods. This is a safe first step (coarse-grained lock); fine-grained locking can be optimized later.

3. **Add model integrity verification** (`services/risk/model.py:24,31`) — **Critical**. Compute SHA-256 hash of model file at deployment time. Verify before `joblib.load()`.

4. **Fix saga TOCTOU** (`__saga__.py:78-100`) — **High**. Hold the lock for the entire duration of `execute_step`, including the `emitter.emit()` call. Alternatively, use a per-saga condition variable.

5. **Fix KeyRotationManager locking** (`__identity__.py:162-187`) — **High**. Add `threading.Lock` to all public methods.

6. **Validate fee input** (`services/fee/service.py:34`) — **High**. Replace `float()` with `get_finite()`.

7. **Remove private key from config serialization** (`__config__.py:188`) — **High**. Exclude `private_key` from `to_dict()` / `save()`.

### Recommended Refactor Roadmap

| Phase | Items | Effort |
|-------|-------|--------|
| **Phase 1: Safety** | C1, C2, C3, H1, H3 | 1-2 days |
| **Phase 2: Concurrency** | H2, H4, M1 (add saga persistence) | 2-3 days |
| **Phase 3: Observability** | L4-L6 (logging gaps), Google-style docstrings, structured logging | 1-2 days |
| **Phase 4: Performance** | M4 (fraud eviction), M5 (executor shutdown), L3 (keys pagination) | 0.5 day |
| **Phase 5: Testing** | Concurrency tests, model integrity tests, signature verification tests | 1-2 days |

### Future Improvement Opportunities

- **Async event bus** — add `asyncio` implementation for FastAPI/uvicorn integration
- **Persistent saga log** — make `SagaOrchestrator` state durable via store backend
- **MechanismService decomposition** — split into domain model + persistence adapter
- **Plugin-based model loading** — strategy pattern for `RiskModel` to support multiple ML frameworks
- **Config-driven fee schedules** — move `FEE_SCHEDULES` from code to configuration
- **Structured logging** — use `structlog` or `logging.StructuredFormatter` with correlation ID context
- **Metrics export** — add Prometheus endpoint for production monitoring
