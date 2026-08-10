# Testing Guide

## Test Suite Overview

59 test files with 828 passing tests. One file per service (`test_<service>.py`), plus infrastructure tests for bus, store, circuit, saga, health, metrics, schema, configuration, identity, authz, tracing, and concurrency. Fault-injection tests are grouped by subsystem.

### Test Structure

| Directory | Purpose |
|-----------|---------|
| `tests/test_<service>.py` | One file per nano-service (29 service-specific files) |
| `tests/test_infrastructure.py` | Bus, store, circuit breaker, schema, metrics, health |
| `tests/test_*_faults.py` | Fault-injection tests (7 files) |
| `tests/test_concurrency.py` | Thread-safety and race-condition tests |
| `tests/test_runtime_e2e.py` | Full Runtime lifecycle (297 lines) |
| `tests/test_saga.py` | Saga orchestration and rollback |
| `tests/test_new_features.py`, `test_new_services.py` | Regression coverage |

### Largest Test Files

| File | Lines | Focus |
|------|-------|-------|
| `test_mechanism.py` | 767 | Core protocol mechanism service |
| `test_framework.py` | 456 | Framework/infrastructure integration |
| `test_runtime_e2e.py` | 297 | Full Runtime lifecycle end-to-end |
| `test_governance.py` | ~200 | Governance param validation |
| `test_fee.py` | 200 | Fee assessment and payment |

---

## Fixtures (conftest.py)

All shared fixtures are defined in `tests/conftest.py`:

| Fixture | Type | Description |
|---------|------|-------------|
| `store` | `MemoryStore` | Fresh in-memory store per test |
| `pg_store` | `PostgresStore` | Postgres-backed store via `testcontainers` (session-scoped `postgres_dsn`) |
| `bus` | `LocalBus` | Fresh local event bus per test |
| `client` | `TestClient` | FastAPI `TestClient` wrapping `create_app()` (requires `serve` extra) |
| `event` | `Event` | Minimal `LOAN_ORIGINATED` event with known payload |
| `tmp_config` | `dict` | Temporary JSON config file + parsed data |

The earlier `fail_store` and `injecting_bus` fixtures were removed
as dead code in the v0.9 hardening pass — neither was imported by
any test file. Tests that need a failing store can construct one
inline; tests that need a failing bus can subclass `LocalBus` and
override `publish` inline.

### Using Fixtures in a Test

```python
def test_store_and_bus(store, bus):
    store.set("k", "v")
    assert store.get("k") == "v"
```

### Writing Tests with pg_store

Requires `testcontainers` and the `postgres` extra:

```python
def test_pg_persistence(pg_store):
    pg_store.set("key", {"nested": True})
    assert pg_store.get("key") == {"nested": True}
```

### Constructing an in-test failing store or bus

The `fail_store` and `injecting_bus` fixtures are no longer
shipped — neither was imported by any test. Tests that need a
failing store or bus should construct one inline:

```python
class FailAfterCountStore(MemoryStore):
    def __init__(self, fail_after: int) -> None:
        super().__init__()
        self._fail_after = fail_after
        self._ops = 0

    def _maybe_fail(self) -> None:
        self._ops += 1
        if self._ops > self._fail_after:
            raise StoreError("simulated failure")

    def set(self, key, value):
        self._maybe_fail()
        return super().set(key, value)


class InjectingBus(LocalBus):
    def publish(self, event):
        raise RuntimeError("injected publish failure")
```

---

## Running Tests

```bash
# Full suite
make test
python -m pytest tests/ -v --tb=short
./test.sh                          # activates .venv, runs with coverage

# Specific file
python -m pytest tests/test_fee.py -v --tb=short

# Specific test
python -m pytest tests/test_fee.py::TestFeeService::test_assesses_fixed_fee -v

# With coverage
python -m pytest tests/ --cov=underwrite --cov-report=term-missing

# With coverage gate (CI default; fails under 80%)
python -m pytest tests/ --cov=underwrite --cov-fail-under=80

# With coverage HTML report
python -m pytest tests/ --cov=underwrite --cov-report=html
open htmlcov/index.html
```

### Configuration

`pyproject.toml` sets defaults:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
asyncio_mode = "auto"
python_files = ["test_*.py"]
```

### Matrix Testing

CI runs against Python 3.10–3.13 plus a separate secrets-scan job
(TruffleHog). Each Python matrix entry installs the dev, risk,
serve, postgres, otlp, vault, and aws extras, then runs:

1. `ruff format --check` (formatting)
2. `ruff check` (lint)
3. `mypy` (types)
4. `bandit` (security)
5. `pip-audit` (dependency audit)
6. `pytest --cov --cov-fail-under=80`

For local matrix testing with tox (optional — CI is the source of
truth), `tox.ini` defines `py39`-`py12` envs; use the Python
version available on the developer machine.

---

## Writing Tests for a Service

### Pattern: Instantiate, Handle, Assert Store

Every service extends `NanoService` and processes events via `handle(event)`. Test by creating a service instance, calling `handle()` with an `Event`, then checking store state and emitted events.

```python
from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__store__ import MemoryStore
from underwrite.services.fee.service import FeeService


def test_fee_assessed_and_stored():
    svc = FeeService(service_id="fee")
    svc.handle(
        Event(
            event_type="fee.assess",
            source="test",
            payload={"loan_id": "L1", "fee_type": "late_payment"},
        )
    )
    keys = svc.store.keys("fee:fee_L1_late_payment_")
    assert len(keys) >= 1
    rec = svc.store.get(keys[0])
    assert rec["amount"] == 25.0
    assert rec["fee_type"] == "late_payment"
```

### Pattern: Assert Emitted Events

Use a `LocalBus` with a wildcard `"*"` subscriber to capture all events:

```python
def test_fee_assess_emits_fee_assessed():
    bus = LocalBus()
    received: list[Event] = []
    bus.subscribe(EventType.FEE_ASSESSED, lambda e: received.append(e))
    svc = FeeService(service_id="fee", bus=bus)
    bus.start()
    svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L2", "fee_type": "service"}))
    assert len(received) == 1
    assert received[0].payload["fee_type"] == "service"
    assert received[0].payload["amount"] == 5.0
```

### Pattern: Reject Invalid Input

Assert the service ignores bad payloads (no store mutations):

```python
def test_rejects_empty_loan_id():
    svc = FeeService(service_id="fee")
    svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "", "fee_type": "late_payment"}))
    assert len(svc.store.keys("fee:")) == 0
```

### Pattern: State Transitions

```python
def test_submit_transitions_to_submitted():
    svc = OriginationService(service_id="origination")
    svc.handle(Event(event_type="origination.create", source="test", payload={"borrower": "carol", "principal": 10000}))
    app_id = svc.store.keys("origination:app_carol_")[0].replace("origination:", "")
    svc.handle(Event(event_type="origination.submit", source="test", payload={"application_id": app_id}))
    rec = svc.store.get(f"origination:{app_id}")
    assert rec["status"] == "submitted"
    assert "submitted_at" in rec
```

### Pattern: Correlation ID Preservation

```python
def test_correlation_id_preserved():
    bus = LocalBus()
    received: list[Event] = []
    bus.subscribe("*", lambda e: received.append(e))
    svc = OriginationService(service_id="origination", bus=bus)
    bus.start()
    svc.handle(
        Event(
            event_type="origination.create",
            source="test",
            payload={"borrower": "f", "principal": 100},
            correlation_id="corr-1",
        )
    )
    emitted = [e for e in received if e.source == "origination"]
    assert emitted[0].correlation_id == "corr-1"
```

### Pattern: Health Check

```python
def test_health_check():
    svc = OriginationService(service_id="origination")
    h = svc.health_check()
    assert h["ok"] is False  # not started
    svc.start()
    h = svc.health_check()
    assert h["ok"] is True
```

---

## Writing Fault Injection Tests

Fault injection tests live in `tests/test_*_faults.py`. Use `fail_store` or `injecting_bus` from conftest to simulate failures.

```python
# tests/test_error_paths.py
def test_store_failure_on_event(fail_store):
    svc = FeeService(service_id="fee", store=fail_store)
    # First set() works, second fails → service should not crash
    svc.handle(Event(event_type="fee.assess", source="test", payload={"loan_id": "L1", "fee_type": "late_payment"}))
    # Event was handled; store error is logged, service continues
```

Fault injection test files:

| File | What it tests |
|------|---------------|
| `test_error_paths.py` | Store failures, bus failures, invalid events |
| `test_concurrency_faults.py` | Race conditions in handlers |
| `test_secrets_faults.py` | Secrets backend failures |
| `test_supervisor_faults.py` | Supervisor restart logic with failures |
| `test_runtime_faults.py` | Runtime lifecycle errors |
| `test_risk_faults.py` | Risk service model failures |
| `test_cli_faults.py` | CLI command error paths |
| `test_validate_faults.py` | Payload validation edge cases |

---

## Writing End-to-End Tests

E2E tests use a `Runtime` instance backed by `MemoryStore`:

```python
from underwrite.__config__ import Configuration
from underwrite.__events__ import Event, EventType
from underwrite.__runtime__ import Runtime


def memory_runtime() -> Runtime:
    cfg = Configuration.default()
    cfg.store.backend = "memory"
    cfg.metrics.enabled = True
    cfg.tracing.enabled = False
    cfg.metrics.export_interval = 0
    cfg.authz.enabled = False
    return Runtime(config=cfg)


def test_full_flow():
    rt = memory_runtime()
    rt.register("mechanism")
    rt.wire("mechanism")
    rt.bus.start()
    rt.start(["mechanism"])
    svc = rt.get("mechanism")
    svc.handle(
        Event(
            event_type="mechanism",
            source="test",
            payload={"command": "add_seed", "user": "bank", "base_budget": 100000},
        )
    )
    state = rt.store.get("protocol:state")
    assert state is not None
    assert "bank" in state["seeds"]
    rt.stop()
```

---

## Tips

- Every service test file uses the naming convention `tests/test_<service>.py` with a `Test<Service>Service` class.
- Use `Event(source="test", source_key="test")` for test events; the actual `source` and `source_key` are set by the emitting service.
- The `event` fixture provides a `LOAN_ORIGINATED` event with `borrower="alice"`, `principal=10000`, `term=12`.
- Store keys follow the pattern `<service_id>:<suffix>_<id>_` (e.g., `fee:fee_L1_late_payment_`).
- Bus subscriptions with `"*"` wildcard capture all event types for assertion.
- Use `pytest.raises` for expected exceptions like `ProtocolError` (non-finite values, oversized payloads).
- `asyncio_mode = "auto"` in `pyproject.toml` enables async test functions without decorators.
