# Contributing to underwrite

## Branching Strategy

All development happens on feature branches forked from `master`. Use one of these prefixes:

| Prefix       | Purpose                          |
|--------------|----------------------------------|
| `feat/`      | New features or services         |
| `fix/`       | Bug fixes                        |
| `refactor/`  | Code restructuring, no new API   |
| `docs/`      | Documentation changes             |
| `test/`      | Test additions or improvements   |

Branch names should be short and descriptive: `feat/sqs-event-bus`, `fix/path-traversal`, `refactor/runtime-factories`.

## PR Process

1. Fork the repository and clone your fork.
2. Create a feature branch from `master`.
3. Make your changes, keeping commits small and focused.
4. Run all checks locally:
   ```bash
   make lint        # ruff check underwrite/ tests/
   make typecheck   # mypy underwrite/
   make test        # pytest tests/ -v --tb=short -q
   ```
5. Commit using [Conventional Commits](https://www.conventionalcommits.org/).
6. Push your branch and open a pull request against `master`.
7. A maintainer will review; address all feedback before merge.

### Review Expectations

- At least one maintainer review is required before merge.
- All CI checks (lint, typecheck, tests across Python 3.10–3.13) must pass.
- New code must include tests that pass.
- Breaking changes must be clearly documented in both the PR description and the changelog.
- Squash-merge is preferred for feature branches; rebase-merge for multi-commit contributions where each commit is independently meaningful.

## Development Setup

```
./setup.sh
```

This creates a `.venv`, installs the package in editable mode with dev extras, copies `.env.example` to `.env`, and runs validation.

Alternatively, manually:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,risk,serve,otlp,vault,aws]"
```

Helper scripts are available:

| Command              | What it does                          |
|----------------------|---------------------------------------|
| `make lint`          | ruff check                            |
| `make typecheck`     | mypy                                  |
| `make test`          | pytest with coverage                  |
| `make clean`         | Remove build/venv/cache artifacts     |
| `./lint.sh`          | ruff check + format check + mypy      |
| `./test.sh`          | pytest with coverage (verbose)        |
| `./format.sh`        | ruff format + ruff check --fix        |
| `./cleanup.sh`       | deep clean of all artifacts           |

## Coding Standards

- **Docstrings**: Google-style. Every public API must have a docstring with `Args:`, `Returns:`, and (where applicable) `Raises:` sections.
- **Type hints**: Required on all public APIs. Use PEP 585 generics (`list[str]` not `List[str]`) and PEP 604 union syntax (`X | None` not `Optional[X]`).
- **Line length**: 120 columns (enforced by ruff).
- **Linter**: ruff with `select = ["E", "F", "I", "UP", "B"]`.
- **Type checker**: mypy with `--ignore-missing-imports`.
- **Visibility**: Double-underscore name mangling (`self.__private_attr`) for implementation details; `@property` accessors to expose them.
- **ABCs**: Abstract base classes for all extensible interfaces (`Store`, `EventBus`, `Core`, `SecretsBackend`).

## Testing Requirements

- **New services** must include a test file under `tests/test_<name>.py` with at minimum:
  - A test for each handler the service registers
  - Edge cases: empty payloads, missing keys, invalid values
  - Integration with the store (round-trip state persistence)
- **Bug fixes** must include a regression test that reproduces the bug and verifies the fix.
- Property-based tests with Hypothesis are encouraged for stateful logic (e.g., delegation graph operations).
- Mutation testing via mutmut is available: `mutmut run`.

The current test suite has **1276 tests** across **72 test files** covering all 34 services, the runtime, bus, store, authz, saga, identity, PII, metrics, configuration, and CLI.

## Documentation

- New features or changed APIs require corresponding updates in `docs/`.
- Keep `mkdocs.yml` nav in sync when adding new documentation pages.
- The doc site builds with `mkdocs build` — verify no broken links or missing pages.
- Inline API documentation changes can go directly in source docstrings (which feed the API reference).

## Commit Message Examples

```
feat: add SQS event bus implementation
fix: prevent path traversal via triple-dot sequences in underwrite.store.Sqlite
refactor: extract factory methods from Runtime into dedicated module
test: add property-based tests for DelegationGraph
docs: update CONTRIBUTING with review expectations
chore: bump cryptography from 41.0 to 42.0
```

Allowed types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `perf`, `security`.

## Security

Vulnerabilities should be reported via the [security policy](https://github.com/sachncs/underwrite/security/policy) — not through public issues. For sensitive findings, email the maintainers directly.

## Questions

Open a [discussion](https://github.com/sachncs/underwrite/discussions) or file an [issue](https://github.com/sachncs/underwrite/issues).
