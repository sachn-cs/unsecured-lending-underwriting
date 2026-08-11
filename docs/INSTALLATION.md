# Installation

## System Requirements

- **Python** >= 3.10
- **pip** (bundled with Python)
- **git** (required for development install and setuptools-scm versioning)

## Production Install

Install from PyPI:

```bash
pip install underwrite
```

Install with extras for additional backends and integrations:

```bash
pip install underwrite[serve]       # HTTP daemon (uvicorn + FastAPI)
pip install underwrite[risk]        # ML risk scoring (numpy, scikit-learn)
pip install underwrite[otlp]        # OpenTelemetry tracing
pip install underwrite[vault]       # HashiCorp Vault secrets backend
pip install underwrite[aws]         # AWS S3 export (boto3)
pip install underwrite[gcs]         # GCS export (google-cloud-storage)
pip install underwrite[security]    # Security audit tooling (bandit, pip-audit)
pip install underwrite[all]         # All extras except [dev] and [security]
```

## Development Install

### Quick Start (recommended)

```bash
./setup.sh
```

This idempotent script:

1. Checks prerequisites (Python >= 3.10, pip, git)
2. Creates a `.venv` virtual environment
3. Upgrades pip, setuptools, and wheel
4. Installs the package in editable mode with `[dev]` extras
5. Installs pre-commit hooks (ruff lint + format, mypy)
6. Copies `.env.example` to `.env` if not present
7. Validates the environment (import check, version, tool availability)

### Manual Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Extras Reference

| Extra       | Packages                                            | Purpose                          |
|-------------|-----------------------------------------------------|----------------------------------|
| `[dev]`     | pytest, pytest-cov, hypothesis, ruff, mypy, bandit, pip-audit, httpx
| `[risk]`    | numpy, scikit-learn                                | ML-based default probability scoring |
| `[serve]`   | uvicorn, fastapi                                    | HTTP daemon for REST API         |
| `[otlp]`    | opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp-proto-grpc, opentelemetry-instrumentation-fastapi | Distributed tracing via OTLP     |
| `[vault]`   | hvac                                               | HashiCorp Vault secrets backend  |
| `[aws]`     | boto3                                              | AWS S3 export (audit, reporting) |
| `[gcs]`     | google-cloud-storage                               | GCS export (audit, reporting)    |
| `[security]`| bandit, pip-audit                                  | Static analysis and dependency auditing |
| `[all]`     | otlp + serve + vault + aws + gcs         | Everything except dev and security |

> **Note:** `[mutation]` extra provides `mutmut` for mutation testing but is not included in `[all]`.

## Docker

Build the image:

```bash
docker build -t underwrite .
```

Run the HTTP daemon:

```bash
docker run -p 8080:8080 underwrite
```

The Docker image uses a multi-stage build (Python 3.12-slim):

- **Builder stage**: builds the wheel and installs the package with `[serve,otlp,vault]` extras
- **Runtime stage**: copies only the installed site-packages, runs as non-root `underwrite` user, exposes port 8080, includes a health check on `/healthz`

## Docker Compose

```bash
docker compose up
```

This starts a single `underwrite` container with:

- Port mapping: `8000:8080`
- Sqlite store backed by a named volume mounted at `/data`
- Services: `mechanism`, `audit`, `risk`, `fraud`
- Rate limit of 100 req/s
- Environment variables read from your `.env` file

## Verify Installation

```bash
python -c "import underwrite; print(underwrite.__version__)"
```

Expected output resembles `0.1.dev65+gad81577c8.d20260608` (version is driven by git tags via setuptools-scm).

## Configuration

Copy the environment template and adjust for your local setup:

```bash
cp .env.example .env
```

All settings are documented with inline comments in `.env.example`. The runtime reads environment variables prefixed with `UNDERWRITE_` (e.g. `UNDERWRITE_STORE_BACKEND`, `UNDERWRITE_LOG_LEVEL`). Alternatively, a `underwrite.json` configuration file can be created via `underwrite init`.
