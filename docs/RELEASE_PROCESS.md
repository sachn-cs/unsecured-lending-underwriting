# Release Process

## Versioning

underwrite uses **Semantic Versioning** via `setuptools-scm`. Version numbers are derived entirely from git tags.

- **Format**: `X.Y.Z` (e.g., `0.1.0`)
- **Dev builds** (untagged commits): `0.1.dev65+gad81577c8.d20260608`
- **Pre-release tags**: `v0.1.0-alpha`, `v0.2.0-beta`

The version is auto-generated at build time and written to `underwrite/__version__.py`:

```python
__version__ = version = "0.1.dev65+gad81577c8.d20260608"
__version_tuple__ = version_tuple = (0, 1, "dev65", "gad81577c8.d20260608")
```

To inspect the current version:
```bash
python -c "import underwrite; print(underwrite.__version__)"
```

## Current Status

**Version**: `0.1.dev65` (pre-production alpha)
**Tests**: 828+ across 59 test files
**Services**: 28 nano-service implementations

The project is pre-v0.1.0. The first stable release will be `v0.1.0`.

## Pre-Release Strategy

| Tag               | Focus                                   |
|-------------------|-----------------------------------------|
| `v0.1.0-alpha`    | Core API finalized; all ABC interfaces stable |
| `v0.2.0-beta`     | Security fixes, observability, saga persistence |
| `v0.3.0-beta`     | Async event bus, Prometheus metrics, config enforcement |

Pre-releases focus on critical bug fixes and blocking issues from the [TODO.md](../TODO.md) audit.

## Release Workflow

### 1. Create Release Branch

```bash
git checkout main
git pull origin main
git checkout -b release/v0.1.0
```

### 2. Run Full Validation

```bash
# Full test suite (828+ tests)
python -m pytest tests/ -v --tb=short --cov=underwrite --cov-report=term-missing

# Lint
ruff check underwrite/ tests/

# Type check
mypy underwrite/

# Security audit
bandit -r underwrite/ -x tests,.venv,.tox
pip-audit
```

All checks must pass before proceeding.

### 3. Update CHANGELOG.md

Move items from `[Unreleased]` to a new `[X.Y.Z] - YYYY-MM-DD` section. Ensure all entries follow Keep a Changelog format. See [CHANGELOG_GUIDE.md](CHANGELOG_GUIDE.md).

### 4. Tag the Release

```bash
# For a stable release
git tag -a v0.1.0 -m "v0.1.0 — Initial stable release"

# For a pre-release
git tag -a v0.1.0-alpha -m "v0.1.0-alpha — API preview"

# Push tags
git push origin v0.1.0
```

Pushing the tag triggers `setuptools-scm` to produce the final version.

### 5. Build Distribution

```bash
python -m build
```

This produces:
- `dist/underwrite-X.Y.Z-py3-none-any.whl` (wheel)
- `dist/underwrite-X.Y.Z.tar.gz` (sdist)

Verify contents:
```bash
tar tzf dist/underwrite-*.tar.gz
```

### 6. Publish to PyPI

```bash
twine check dist/*
twine upload dist/*
```

Requires PyPI credentials with push access to the `underwrite` project.

### 7. Build and Push Docker Image

```bash
docker build -t underwrite:0.1.0 -t underwrite:latest .
docker tag underwrite:0.1.0 ghcr.io/sachncs/underwrite:0.1.0
docker push ghcr.io/sachncs/underwrite:0.1.0
```

The `Dockerfile` uses a multi-stage build (builder → slim runtime) with Python 3.12.
It exposes port `8080` and runs `underwrite serve` by default.

### 8. Merge Release Branch

```bash
git checkout main
git merge --no-ff release/v0.1.0
git push origin main
```

Delete the release branch:
```bash
git branch -d release/v0.1.0
git push origin --delete release/v0.1.0
```

## CI/CD Pipeline

The GitHub Actions pipeline (`.github/`) runs on every push and pull request:

- **Python matrix**: 3.10, 3.11, 3.12, 3.13
- **Steps**: lint → typecheck → test → (publish only on tags)

The `make` targets used by CI:
```bash
make lint
make typecheck
make test
```

## Production Deployment Checklist

Before deploying to production, verify the following:

- [ ] **Authorization enabled**: Bearer token auth configured in config
- [ ] **Postgres configured**: `store.backend = "postgres"` with connection string
- [ ] **API token set**: `UNDERWRITE_API_TOKEN` or `UNDERWRITE_AUTHZ_TOKEN`
- [ ] **Tracing enabled**: OTLP exporter configured (`tracing.exporter = "otlp"`)
- [ ] **Metrics enabled**: Prometheus endpoint on `/metrics`
- [ ] **Secrets backend configured**: Vault or AWS Secrets Manager (not env vars)
- [ ] **Saga persistence enabled**: `saga.store_backend = "file"` or `"postgres"`
- [ ] **Rate limiting configured**: Non-default rate limits per subscriber
- [ ] **Health checks passing**: `/healthz` and `/readyz` return 200
- [ ] **PII redaction enabled**: `logging.redact_pii = true`
- [ ] **Graceful shutdown timeout**: Set via config or env
- [ ] **Docker image tagged**: With release version, not just `latest`
- [ ] **Database migrations run**: `underwrite migrate` executed
- [ ] **Audit trail verified**: Events being written to audit ledger

## Rolling Back

If a release introduces a critical issue:

1. Identify the last stable tag: `git tag --sort=-version:refname`
2. Revert the release commit on `main`: `git revert HEAD`
3. Push the revert and tag a patch release: `v0.1.1`
4. Update the Docker image tag to the patch version
5. Notify downstream consumers

For database schema migrations, use the migration engine (`__migrate__.py`) to apply rollback migrations if available.
