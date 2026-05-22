# underwrite — Delegated Underwriting Protocol

A **nano-service platform** for unsecured lending underwriting. Each service is independently deployable, configuration-driven, and communicates over a shared in-process event bus with cryptographic attestation.

## Features

- **28 nano-services** — risk scoring, fraud detection, KYC/AML, collateral management, loan origination, collections, recovery, governance, and more
- **Event-driven architecture** — services communicate via typed events with Ed25519 signatures
- **Saga orchestration** — distributed transaction coordination with automatic rollback
- **Pluggable backends** — in-memory, filesystem, or Postgres for state; local or cloud for event bus
- **Built-in resilience** — circuit breakers, dead-letter queues, idempotency guards, retry policies
- **Production observability** — distributed tracing, metrics collection, health checks, structured logging
- **Type-safe** — fully typed with PEP 585/604 generics, `py.typed` marker, ruff-clean

## Installation

```bash
pip install underwrite

# With risk scoring (scikit-learn)
pip install "underwrite[risk]"

# With Postgres backend
pip install "underwrite[postgres]"

# Development
pip install "underwrite[dev,risk,postgres]"
```

## Quick Start

```python
from underwrite import Runtime, Configuration

# Load config
config = Configuration.load("config.json")

# Start runtime
rt = Runtime(config=config)
rt.start()

# Runtime handles event dispatch, health checks, and lifecycle
rt.stop()
```

## CLI Usage

```bash
# Show available services
underwrite list

# Run specific services
underwrite run mechanism risk audit

# Health check
underwrite health

# View dead letter queue
underwrite dlq

# Metrics snapshot
underwrite metrics
```

## Development

```bash
# Install in editable mode with dev extras
pip install -e ".[dev,risk,postgres]"

# Run tests
make test

# Lint
make lint

# Type check
make typecheck

# Build distribution
make build
```

## Testing

```bash
pytest tests/ -v --tb=short
```

## Project Structure

```
underwrite/             # Source package
  __init__.py           # Public API exports
  __bus__.py            # Event bus (pub/sub)
  __store__.py          # State store (memory/file/postgres)
  __saga__.py           # Saga orchestrator
  __authz__.py          # Access control & signature verification
  __circuit__.py        # Circuit breaker & retry
  __config__.py         # Configuration engine
  __runtime__.py        # Service lifecycle manager
  __cli__.py            # CLI (typer-based)
  services/             # 28 nano-service implementations
    base.py             # NanoService ABC
    mechanism/          # Core state machine
    risk/               # ML risk scoring
    fee/                # Fee assessment
    audit/              # Event audit log
    ...
tests/                  # Test suite (separate from source)
docs/                   # Documentation
```

## Architecture

Each nano-service extends `NanoService` and implements a single `handle(event)` method. Services:

1. Subscribe to event types via the shared bus
2. Receive events through `__dispatch` (handles authz, idempotency, tracing, metrics)
3. Emit new events with Ed25519 signatures via `emit()`
4. Persist state through the `Store` abstraction

Cross-cutting concerns (authz, tracing, metrics, sagas) are injected, not inherited.

## License

MIT — see [LICENSE](LICENSE) for details.
