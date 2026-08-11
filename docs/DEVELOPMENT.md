# Development

## Local Setup

```bash
./setup.sh
```

This bootstraps the entire environment. See [INSTALLATION.md](INSTALLATION.md) for details.

## Available Scripts

| Script          | Action                                                       |
|-----------------|--------------------------------------------------------------|
| `./setup.sh`    | Idempotent environment bootstrap (venv, deps, pre-commit)    |
| `./lint.sh`     | Run ruff check, ruff format check, and mypy                  |
| `./format.sh`   | Auto-format all Python files with ruff (format + check --fix) |
| `./test.sh`     | Run pytest with coverage (`--cov=underwrite --cov-report=term-missing`) |
| `./cleanup.sh`  | Remove all build, test, cache, and virtual environment artifacts |

## Makefile Targets

| Target       | Command                                    | Description                          |
|--------------|--------------------------------------------|--------------------------------------|
| `make install` | `pip install -e .`                       | Minimal editable install             |
| `make dev`   | `pip install -e ".[dev,risk,serve,otlp,vault,aws]"`    | Install dev, risk, serve and integrations |
| `make test`  | `python -m pytest tests/ -v --tb=short -q` | Run the test suite                   |
| `make lint`  | `ruff check underwrite/`                   | Lint with ruff                       |
| `make typecheck` | `mypy underwrite/`                     | Static type checking                 |
| `make build` | `python -m build`                          | Build wheel + sdist                  |
| `make clean` | `rm -rf build/ dist/ *.egg-info ...`       | Remove all build artifacts           |

## Pre-commit Hooks

Defined in `.pre-commit-config.yaml`:

- **ruff** (v0.9.0) — lint check with `--fix`
- **ruff-format** — format check
- **mypy** (v1.14.0) — static type checking

Hooks run on every `git commit`. Install them via `./setup.sh` or manually:

```bash
pip install pre-commit && pre-commit install
```

## Code Structure Conventions

```
underwrite/
├── init.py            # Public API exports
├── cli.py             # Typer CLI (run, health, dlq, metrics, serve, etc.)
├── config.py          # Configuration model (Pydantic)
├── runtime.py         # Runtime — service lifecycle manager
├── handler.py # SERVICE_MAP, SERVICE_CLASSES, WIRING constants
├── bus.py             # Event bus (pub/sub, DLQ, idempotency)
├── events.py          # Event envelope + EventType enum
├── store.py           # Sqlite store (stdlib sqlite3) with WAL + busy_timeout
├── health.py          # Health check registry
├── metrics.py         # Metrics collector
├── tracer.py          # Distributed tracing
├── saga.py            # Saga orchestration
├── identity.py        # Ed25519 identity management
├── authz.py           # Access control
├── secrets.py         # Secrets manager (env, Vault)
├── supervisor.py      # Auto-recovery for failed services
├── migrate.py         # Schema migration framework
├── __pii.py               # PII redaction
├── schema.py          # Schema validation
├── validate.py            # Payload validation helpers
├── services/
│   ├── base.py            # NanoService and StatefulService ABCs
│   ├── persistence.py     # TypedStoreRepository, BatchedStoreRepository
│   └── <service>/         # One directory per service
│       ├── init.py
│       └── service.py     # Service class extending NanoService
```

### Service Conventions

Each nano service:

- Lives in its own directory under `underwrite/services/<name>/`
- Has an `init.py` (may be empty) and a `service.py`
- Defines a class that extends `NanoService` (or `StatefulService` for stateful services)
- Implements `handle(self, event: Event) -> None` to process incoming events
- Uses `self.emit(event_type, payload, correlation_id=...)` to publish outgoing events
- Can override `health_check(self) -> dict[str, Any]` for service-specific health
- Uses `self.store` for persistence and `self.state_lock` for thread-safe state mutation

### Event Bus Wiring

The `WIRING` dictionary in `handler.py` maps each `EventType` to the list of services that should receive it. Services are automatically subscribed at startup by the `Runtime.wire()` method.

### Example Service

```python
from underwrite.message import Event, EventType
from underwrite.logger import logger
from underwrite.services.base import NanoService


class MyService(NanoService):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def handle(self, event: Event) -> None:
        if event.event_type == EventType.SOME_EVENT:
            result = do_work(event.payload)
            self.emit("my.event.processed", {"result": result}, correlation_id=event.correlation_id)

    def health_check(self) -> dict:
        return {**super().health_check(), "my_metric": 42}
```

## Adding a New Service

1. **Create the service module:**

   ```bash
   touch underwrite/services/newservice.py
   ```

   For services with helper sub-modules, create a package instead:

   ```bash
   mkdir underwrite/services/newservice
   touch underwrite/services/newservice/__init__.py
   touch underwrite/services/newservice/newservice.py
   ```

2. **Write the service class** in `underwrite/services/newservice.py` (or `underwrite/services/newservice/newservice.py` for packages), extending `Core` (stateless) or `StatefulService` and implementing `handle()`. Add the import to `__init__.py` if the module is a package:

   ```python
   from underwrite.services.newservice.newservice import Handler
   __all__ = ["Handler"]
   ```

3. **Register in the service registry** (`handler.py`):
   - Add an entry to `HANDLER_MAP`: `"newservice": "underwrite.services.newservice"` (flat) or `"underwrite.services.newservice"` (package — the `__init__.py` re-exports `Handler`).
   - Add an entry to `HANDLER_CLASSES`: `"newservice": "Handler"`
   - Add the service name to the subscriber list in `WIRING` for each `EventType` it should receive.
   - Optionally add the name to `HANDLER_NAMES` (auto-derived from `HANDLER_CLASSES.keys()` in `config.py`).

4. **Write tests** in `tests/` following existing patterns.

## Debugging

- **Failed events**: `underwrite dlq` shows all dead-lettered events with the subscriber and error message. Use `underwrite dlq --replay` to re-publish them after fixing the issue.
- **Verbose logging**: `underwrite --log-level DEBUG run mechanism` (note: pass `--log-level` before the command) or set `UNDERWRITE_LOG_LEVEL=DEBUG` in `.env`.
- **Store inspection**: The filesystem store writes to `./data/` by default; raw state is serialized as JSON blobs.
- **Service isolation**: Services can be started individually in separate terminal sessions for focused debugging.
- **No-op risk model**: If `scikit-learn` is not installed, `RiskService` falls back gracefully with `HAS_RISK_MODEL = False`.
