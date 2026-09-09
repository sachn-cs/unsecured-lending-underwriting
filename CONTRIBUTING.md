# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Code Style

- **Linter**: ruff (`ruff check underwrite/ tests/`)
- **Type checker**: mypy (`mypy underwrite/`)
- **Docstrings**: Google-style
- **Line length**: 120 columns

## Running Tests

```bash
python -m pytest tests/ -q
```

With coverage:

```bash
python -m pytest tests/ --cov=underwrite -q
```

## Running Lint

```bash
ruff check underwrite/ tests/
```

## Running Type Check

```bash
mypy underwrite/
```

## PR Process

1. Fork the repository.
2. Create a feature branch (`git checkout -b feat/my-feature`).
3. Make your changes.
4. Ensure all checks pass (lint, typecheck, tests).
5. Commit using [Conventional Commits](https://www.conventionalcommits.org/).
6. Open a PR against `master`.
7. All checks must pass before merge.

## Commit Messages

Use Conventional Commits style:

```
feat: add OTLP auto-instrumentation for FastAPI
fix: handle corrupted audit JSONL lines gracefully
refactor: extract store validation into shared module
test: add concurrency tests for bus and store
docs: update CONTRIBUTING with test commands
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`.
