# Code Style Guide

This document reflects the conventions observed throughout the underwrite codebase. All contributions must adhere to these standards.

## Python Version Target

**Python 3.10+** — enforced via `pyproject.toml` (`requires-python = ">=3.10"`) and ruff (`target-version = "py310"`).

This permits:
- **PEP 585** — built-in generics (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`) instead of `typing.List`, `typing.Dict`, etc.
- **PEP 604** — union syntax (`X | None` instead of `Optional[X]`, `str | int` instead of `Union[str, int]`)
- **PEP 636** — structural pattern matching (`match`/`case`)

## Line Length

**120 columns**. Configured in `pyproject.toml`:
```toml
[tool.ruff]
line-length = 120
```

## Docstrings

**Google-style** throughout. Every public module, class, method, and function must have a docstring.

```python
def safe_store_get(self, key: str, default: Any = None) -> Any | None:
    """Get a value from the store, logging and returning *default* on failure.

    Args:
        key: Store key to retrieve.
        default: Value returned when the key is missing or the read fails.

    Returns:
        The stored value, *default* if the key is missing, or *default*
        if the read raises an exception.
    """
```

Format:
- Summary line (imperative) followed by a blank line.
- `Args:` — one line per parameter, no types (types are in the signature).
- `Returns:` — description of the return value.
- `Raises:` — optional, documents expected exceptions.
- Use backticks for parameter names and values.

Module-level docstrings describe the module's purpose:
```python
"""In-process event bus for nano-service communication.

This is the **local** backend — a synchronous, thread-safe, in-process
pub-sub bus.  Production deployments swap this for SQS or Modal queues
via configuration; the ``EventBus`` interface remains the same.
"""
```

## Linter

**ruff** configured in `pyproject.toml`:
```toml
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

| Code | Rule set         |
|------|------------------|
| E    | pycodestyle      |
| F    | Pyflakes         |
| I    | isort (imports)  |
| UP   | pyupgrade        |
| B    | flake8-bugbear   |

Run: `ruff check underwrite/ tests/`

Auto-format: `ruff format underwrite/ tests/`

## Type Checker

**mypy** configured in `pyproject.toml`:
```toml
[tool.mypy]
ignore_missing_imports = true
```

Run: `mypy underwrite/`

- Type hints required on all public APIs.
- Use `TYPE_CHECKING` guards for import cycles:
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from underwrite.services.persistence import BatchedStoreRepository
  ```
- Prefer `from __future__ import annotations` in every file to allow forward references without quotes.
- Protocol classes for structural typing:
  ```python
  class Connection(Protocol):
      def cursor(self) -> Any: ...
      @property
      def closed(self) -> bool: ...
  ```

## Naming Conventions

| Category              | Convention         | Examples                              |
|-----------------------|--------------------|---------------------------------------|
| Functions/variables   | `snake_case`       | `get_log_correlation_id()`, `sync_interval` |
| Classes               | `PascalCase`       | `NanoService`, `DeadLetterQueue`, `LocalBus` |
| Constants             | `UPPER_CASE`       | `MAX_PAYLOAD_SIZE`, `EPSILON`, `FILE_TIMEOUT_MSG` |
| Private attributes    | `__double_underscore` | `self.__service_id`, `self.__batch_lock` |
| Public methods        | `snake_case`       | `safe_store_get()`, `force_sync()`    |
| Abstract methods      | `snake_case`       | `handle()`, `do_sync_store()`         |
| Modules               | `snake_case`       | `__store__.py`, `prometheus_export.py` |
| Type variables        | `_T` short form    | `_T = TypeVar("_T")`                  |

## Visibility

- **Double-underscore name mangling** for private implementation details:
  ```python
  self.__service_id: str = service_id
  self.__batch_lock: threading.Lock = threading.Lock()
  ```
- **`@property` accessors** to expose private attributes read-only:
  ```python
  @property
  def service_id(self) -> str:
      return self.__service_id
  ```
- **`__all__`** explicitly in every public module to define the public surface:
  ```python
  __all__ = ["Event", "EventType", "MAX_PAYLOAD_SIZE"]
  ```

## ABC Pattern

Abstract base classes define every extensible interface. Use `ABC` + `@abstractmethod`:

```python
class Store(ABC):
    """Abstract key-value store.  Thread-safe."""

    @abstractmethod
    def get(self, key: str) -> Any | None: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...
```

Key ABCs in the codebase:

| ABC                  | File             | Implementations                       |
|----------------------|------------------|---------------------------------------|
| `Store`              | `__store__.py`   | `MemoryStore`, `FileStore`, `PostgresStore` |
| `EventBus`           | `__bus__.py`     | `LocalBus`, `AsyncLocalBus`           |
| `NanoService`        | `services/base.py` | 28 service classes                  |
| `StatefulService`    | `services/base.py` | Services with mutable state         |
| `SecretsBackend`     | `__secrets__.py` | `EnvSecretsBackend`, `VaultSecretsBackend`, `AwsSecretsBackend` |

## Exception Hierarchy

All exceptions inherit from `UnderwriteError` (defined in `__exceptions__.py`):

```
UnderwriteError
├── ConfigurationError
├── ServiceNotFoundError
├── IdentityError
├── BusError
├── StoreError
├── ProtocolError
│   ├── UnknownUserError
│   ├── InvariantViolationError
│   └── InfeasibleOperationError
├── AuthzError
├── RateLimitError
├── MigrationError
├── SagaError
└── CircuitBreakerOpenError
```

## Module Organization

- **Core infrastructure**: Single-role modules prefixed `__` under `underwrite/`:
  - `underwrite.__store__` — `Store` ABC and implementations
  - `underwrite.__bus__` — `EventBus` ABC and implementations
  - `underwrite.__config__` — Configuration loading and validation
  - `underwrite.__runtime__` — Runtime lifecycle management
  - `underwrite.__serve__` — FastAPI HTTP server
  - `underwrite.__cli__` — Typer CLI entry point
- **Services**: Each as a sub-package under `underwrite/services/<name>/` with `__init__.py` + `service.py`
- **Utilities**: Standalone modules like `validate.py`, `prometheus_export.py`

## Import Order

Imports are grouped in three blocks separated by blank lines, each sorted alphabetically:

1. **Python standard library**
2. **Third-party packages**
3. **Underwrite package**

```python
import concurrent.futures
import json
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pytest

from underwrite.__bus__ import LocalBus
from underwrite.__config__ import Configuration
```

ruff with `select = ["I"]` enforces this automatically via `ruff check --fix`.

## `__init__.py` Conventions

Top-level `__init__.py` re-exports public API and defines `__all__`:

```python
from underwrite.__bus__ import EventBus, LocalBus
from underwrite.__exceptions__ import (
    BusError,
    ConfigurationError,
    UnderwriteError,
)
from underwrite.services import NanoService

__all__: list[str] = ["Runtime", "Configuration", "NanoService", "Event", ...]
```

## Dataclass Usage

Prefer `@dataclass(frozen=True, slots=True)` for immutable data carriers:

```python
@dataclass(frozen=True, slots=True)
class Event:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
```

Use `field(default_factory=...)` for mutable defaults.

## File Headers

Every `.py` file starts with a module-level docstring:

```python
"""Domain events shared across all nano services."""
```

When `from __future__ import annotations` is used (preferred), place it immediately after the docstring:

```python
"""Persistence abstraction for state and log storage."""

from __future__ import annotations
```

## Concurrency

- Thread safety via `threading.Lock` and `threading.RLock` (reentrant).
- `ThreadPoolExecutor` for concurrent handler dispatch (configurable `max_concurrent`).
- `threading.local()` for per-thread context (e.g., correlation IDs).
- Avoid `asyncio` outside `__async_bus__.py` — the core runtime is synchronous.

## Testing Conventions

- One test file per service: `tests/test_<name>.py`.
- Test classes prefixed `Test`; methods prefixed `test_`.
- Use `tmp_path` fixture for file-based tests.
- Use `monkeypatch` for environment variable overrides.
- Type hint all test functions: `def test_something(self) -> None:`.
- Test modules also use `from __future__ import annotations`.
