# Dependencies

This document describes every Python dependency of the underwrite platform, where it is used in the codebase, and considerations when upgrading.

---

## Core Dependencies

These are declared in `[project.dependencies]` of `pyproject.toml` and are always installed.

### cryptography >=41.0

| Detail | Description |
|--------|-------------|
| **Purpose** | Ed25519 asymmetric key management, event signing, and signature verification. |
| **Modules** | `underwrite/identity.py` — `Identity.create()`, `Identity.sign()`, `Identity.verify()`, `Identity.persist()`; `underwrite/authz.py` — `AccessControl.verify_signature()` |
| **Upgrade considerations** | Ed25519 API is stable across 41.x–43.x. The `cryptography.hazmat.primitives.asymmetric.ed25519` module is used directly (not `SigningKey` from `nacl`). If upgrading past 43.x, check for deprecation of `BestAvailableEncryption` and `serialization` helpers. |

### typer >=0.12

| Detail | Description |
|--------|-------------|
| **Purpose** | CLI framework for the `underwrite` command-line tool. |
| **Modules** | `underwrite/cli.py` — all CLI commands (`init`, `run`, `list`, `identity`, `health`, `dlq`, `metrics`, `serve`, `migrate`) |
| **Upgrade considerations** | typer 0.12+ uses Click 8.x internally. Breaking changes are rare. If upgrading to typer 0.15+, verify that `no_args_is_help` still works and `typer.Argument(...)` with `metavar` renders correctly. |

### pydantic >=2.0

| Detail | Description |
|--------|-------------|
| **Purpose** | Configuration schema validation and serialisation. |
| **Modules** | `underwrite/config.py` — all config classes (`Configuration`, `BusConfig`, `StoreConfig`, `IdentityConfig`, etc.) use `BaseModel` with `Field`, `field_validator`, and `model_config = {"extra": "forbid"}`. |
| **Upgrade considerations** | pydantic v2 is required. v1 style (`BaseSettings`, `validator`) is not used. If upgrading to pydantic v3, watch for changes to `model_copy()`, `model_dump()`, and `field_validator` signature. The codebase uses `model_copy(update=...)` in `Configuration.__merge` which is v2-specific. |

---

## Optional Dependencies

Each group is declared in `[project.optional-dependencies]` and must be installed separately.

### dev (development)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `pytest` | >=7.4 | `tests/` | Test framework. Configured in `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`. |
| `pytest-cov` | >=5.0 | `tests/` (via `tox.ini`/`Makefile`) | Coverage reporting. |
| `hypothesis` | >=6.0 | `tests/` | Property-based testing for state-machine invariants. |
| `ruff` | >=0.6 | Project-wide | Linter and formatter. Configured in `[tool.ruff]` with `select = ["E", "F", "I", "UP", "B"]`. |
| `mypy` | >=1.10 | Project-wide | Static type checking. Configured in `[tool.mypy]` with `ignore_missing_imports = true`. |
| `bandit` | >=1.7 | Security scanning | Also part of `security` extra. Configured in `[tool.bandit]`. |
| `pip-audit` | >=2.7 | Security scanning | Also part of `security` extra. |
| `testcontainers` | >=4.0 | Integration tests | Docker-based Postgres test containers. |
| `httpx` | >=0.27 | Tests for `serve` | Async HTTP client for testing FastAPI endpoints. |

**Upgrade considerations**: ruff 0.6+ may introduce new lint rules; pin or update `select` accordingly. mypy 1.10+ is compatible with Python 3.10–3.13. `testcontainers` 4.x requires Docker to be running.

### risk (risk scoring)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `numpy` | >=1.26 | `underwrite/services/risk/model.py` (transitive via sklearn) | Numerical operations in risk model. |
| `scikit-learn` | >=1.5 | `underwrite/services/risk/model.py` | ML model loading (joblib) and prediction via `JoblibModelStrategy`. |

**Upgrade considerations**: scikit-learn 1.5+ drops Python 3.9 support (already satisfied). Joblib model serialization format is backward-compatible within the 1.x line. The `JoblibModelStrategy` requires `UNDERWRITE_ALLOW_JOBLIB=true` to activate joblib loading (see `identity.py` line 234–248 for the gating logic).

### postgres

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `psycopg2-binary` | >=2.9 | `underwrite/store.py` (PostgresStore) | PostgreSQL connection pool (`psycopg2.pool.ThreadedConnectionPool`) with circuit breaker and retry policy. |

**Upgrade considerations**: `psycopg2-binary` 2.9 is the last major version (maintenance-only). Consider migrating to `psycopg[c]` 3.x for the `postgres` extra. The API differences (connection pool API, cursor context managers) would require changes in `PostgresStore.__connection()` and `__execute()`.

### serve (HTTP gateway)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `uvicorn[standard]` | >=0.24 | `underwrite/cli.py` (`serve` command) | ASGI server for the FastAPI app. |
| `fastapi` | >=0.104 | `underwrite/serve.py` | HTTP API framework providing `/v1/health`, `/v1/metrics`, `/v1/publish` endpoints. |

**Upgrade considerations**: FastAPI 0.104+ uses Pydantic v2 exclusively. The `@app.on_event("startup")`/`("shutdown")` decorators used in `serve.py` are deprecated in FastAPI 0.110+ in favour of the lifespan pattern (`@asynccontextmanager`). A migration would replace `on_event` with `lifespan`.

### otlp (OpenTelemetry)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `opentelemetry-api` | >=1.20 | `underwrite/tracer.py` | OTLP span exporter (`OtlpSpanExporter`). |
| `opentelemetry-sdk` | >=1.20 | `underwrite/tracer.py` | SDK tracer provider, batch span processor. |
| `opentelemetry-exporter-otlp-proto-grpc` | >=1.20 | `underwrite/tracer.py` | gRPC OTLP exporter. |
| `opentelemetry-instrumentation-fastapi` | >=0.41b0 | `underwrite/serve.py` | Auto-instrumentation of FastAPI routes via `FastAPIInstrumentor`. |

**Upgrade considerations**: The OTel Python SDK 1.20+ is stable. The `FastAPIInstrumentor` is in beta (`0.41b0`). When upgrading, verify that `BatchSpanProcessor.force_flush()` is still the recommended shutdown pattern. The `Resource.create()` call in `_lazy_init()` is the standard approach for service naming.

### vault (HashiCorp Vault)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `hvac` | >=2.0 | `underwrite/secrets.py` (`VaultSecretsBackend`) | KV v2 secret read/write against Vault. |

**Upgrade considerations**: hvac 2.x API is stable. The code uses `secrets.kv.v2.read_secret_version()` and `secrets.kv.v2.create_or_update_secret()`. If upgrading to hvac 3.x, check for any changes to the KV v2 path resolution.

### aws (AWS Secrets Manager)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `boto3` | >=1.33 | `underwrite/secrets.py` (`AwsSecretsBackend`); `underwrite/services/audit/service.py` (`__export_s3`) | AWS Secrets Manager read/write; S3 audit export. |

**Upgrade considerations**: boto3 1.33+ follows the AWS SDK for Python (v3). The `get_secret_value()` and `put_secret_value()` APIs are stable. The S3 `put_object` API used in audit export is unchanged.

### gcs (Google Cloud Storage)

| Dependency | Version | Used In | Purpose |
|------------|---------|---------|---------|
| `google-cloud-storage` | >=2.10 | `underwrite/services/audit/service.py` (`__export_gcs`) | GCS audit export. |

**Upgrade considerations**: The `storage.Client()` and `bucket().blob().upload_from_string()` API is stable across 2.x. Authentication follows Google's `GOOGLE_APPLICATION_CREDENTIALS` env var.
