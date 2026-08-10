<p align="center">
  <h1 align="center">Underwrite</h1>
  <p align="center">Indian Lending Platform (Beta) — nano-service event-driven architecture with Ed25519 cryptographic attestation.</p>
  <p align="center">
    <a href="#installation"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
    <a href="https://github.com/sachncs/underwrite/actions"><img src="https://img.shields.io/github/actions/workflow/status/sachncs/underwrite/ci.yml?branch=master" alt="CI"></a>
    <a href="https://pypi.org/project/underwrite/"><img src="https://img.shields.io/pypi/v/underwrite" alt="PyPI"></a>
    <a href="https://github.com/sachncs/underwrite/stargazers"><img src="https://img.shields.io/github/stars/sachncs/underwrite" alt="Stars"></a>
  </p>
</p>

**A nano-service platform for Indian retail lending. Designed for RBI Digital Lending Guidelines compliance, with DPDPA 2023 data protection and 30+ independently deployable services connected by an event bus with Ed25519 cryptographic attestation.**

> **Beta — not yet production-ready.** Known gaps include stubbed PAN / Aadhaar / CKYC / CIBIL integrations, no video KYC, stubbed e-NACH / UPI Autopay mandate collection, basic RBAC only, undocumented disaster-recovery procedures, and rough developer experience (no prebuilt Docker images, no Helm charts, manual service wiring required). See [Status](#status) below.

## Features

- **34 wired nano-services + 4 KYC provider clients** — KYC / AML (PAN + Aadhaar Verhoeff), CIBIL / Experian / Equifax credit bureau, CKYC registry, RBI rate-capped pricing, KFS generation, DPDPA consent + DSR, Razorpay PG, risk scoring, fraud detection, collections, recovery, notifications, governance
- **Event-driven** — Typed events with Ed25519 signatures, saga orchestration, dead-letter queues, circuit breakers
- **Pluggable backends** — Memory / filesystem / Postgres stores; local / SQS / Modal event bus; console / OTLP tracing
- **1167 tests** — Rate limiting, idempotency guards, PII redaction, Prometheus metrics
- **DPDPA 2023 + RBI DLG aligned** — Per-product rate caps, all-in-cost APR, penal-interest cap, KFS cooling-off, consent lifecycle, DSR fulfillment, breach notification, auto-purge

## Status

This is the v0.9 release line. Security and correctness fixes from
the hardening pass:

- Ed25519 event signatures bind the source and enforce a 5-minute
  replay window; private keys persist through the configured
  `SecretsManager`.
- `/v1/publish` binds the publisher identity from the request
  payload, with an optional authz gate.
- PII is redacted at the audit, DLQ, and Prometheus tag boundaries
  with token-based field matching.
- DLQ, bus buffer, and idempotency guard are bounded against
  unbounded memory growth.
- Config redaction covers every secret-shaped field; config
  `data_dir` is validated against sensitive system paths.
- Indian holiday calendar covers 2025–2030 with a sensible
  fallback for unknown years.
- KFS APR math, pricing EMI, NPA thresholds, and the
  underwriter rule engine are all aligned with RBI norms.
- **Real KYC provider integrations** — PAN (NSDL/ITD), Aadhaar
  (UIDAI KUA), CIBIL, and CKYC have full wire-protocol clients
  in `services/kyc_providers/`. They are wired into the compliance
  and credit-bureau services and configured via
  `Configuration.kyc_providers`.
- **Production Docker image** — multi-stage build, non-root
  user, healthcheck, OCI labels, Buildx + GitHub Actions
  workflow. Build with `./scripts/build-image.sh` or
  `docker build -t underwrite:dev .`.
- **CI matrix 3.10-3.13**, coverage gate 80%, ruff format check,
  TruffleHog secret scan, mypy / bandit / pip-audit.

Remaining work to reach v1.0:

- Video KYC provider integration (Digilocker, NSDL).
- Helm chart for k8s deployment.
- Pre-built multi-arch (amd64 + arm64) images.
- Read-only `underwrite` role for `psql` / Vault operations.
- Production runbook for on-call (incident response, key
  rotation, DLQ replay).

## Installation

### From PyPI

```bash
pip install underwrite
pip install "underwrite[risk,serve,postgres,otlp,vault,aws]"
```

### From source

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate
pip install -e ".[dev,risk,serve,postgres,otlp,vault,aws]"
```

| Extra | Provides |
|-------|----------|
| `risk` | NumPy, scikit-learn — ML risk models |
| `serve` | Uvicorn, FastAPI — HTTP server |
| `postgres` | psycopg2-binary — Postgres state store |
| `otlp` | OpenTelemetry SDK — distributed tracing |
| `vault` | hvac — HashiCorp Vault secrets |
| `aws` | boto3 — SES, SQS, Secrets Manager |
| `security` | bandit, pip-audit — vulnerability scanning |
| `dev` | pytest, ruff, mypy, hypothesis, testcontainers |

### Prerequisites

- **Python 3.10+**
- **PostgreSQL 14+** (optional — memory / filesystem backends work without it)
- **Docker** (optional — for `docker compose up` with Postgres + Vault + OTLP)

## Quick Start

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate
python -m pytest tests/ --tb=short -q   # 1167 tests
```

To run an Indian lending scenario:

```bash
underwrite init
# edit underwrite.json to enable: mechanism,audit,risk,fraud,compliance,consent,credit_bureau,kfs,pricing,underwriter,decision
underwrite run mechanism audit risk fraud compliance consent credit_bureau kfs pricing underwriter decision
# In another terminal:
python docs/examples/indian_lending.py
# See docs/QUICKSTART.md for the full walkthrough
```

## CLI

```
underwrite

Commands:
  init [PATH]              Create default config
  run <service>...         Start one or more services
  list                     List all 34 wired nano-services
  identity <service>       Generate Ed25519 keypair
  health                   System health status
  dlq [--replay] [--max N] Show or replay dead-letter queue
  metrics                  Metrics snapshot (Prometheus-format on /v1/metrics)
  migrate                  Run pending schema migrations
  serve                    Start HTTP daemon (requires [serve] extra)
```

### HTTP API (with `underwrite serve`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz` | GET | Liveness probe |
| `/readyz` | GET | Readiness probe |
| `/v1/health` | GET | Full system health |
| `/v1/metrics` | GET | Prometheus-format metrics |
| `/v1/publish` | POST | Publish a domain event |

Authentication via `Authorization: Bearer <token>` when started with `--require-auth`.

## Configuration

Configure via **JSON file** (created with `underwrite init`), **env vars**, or both (env vars override). See [`.env.example`](.env.example) for every supported variable — including RBI pricing caps, AML thresholds, credit-bureau API keys, Razorpay credentials, and DPDPA retention periods.

| Setting | Env Variable | Default | Description |
|---------|--------------|---------|-------------|
| State backend | `UNDERWRITE_STORE_BACKEND` | `memory` | `memory` / `file` / `postgres` |
| Store DSN | `UNDERWRITE_STORE_DSN` | — | e.g. `postgresql://user:pass@localhost:5432/underwrite` |
| Personal-loan rate cap | `UNDERWRITE_PERSONAL_LOAN_RATE_CAP` | `0.28` | RBI cap |
| Penal interest cap | `UNDERWRITE_PENAL_INTEREST_CAP` | `0.24` | RBI cap |
| Bearer auth | `UNDERWRITE_REQUIRE_AUTH` | `false` | Require bearer token on `/v1/*` |

## Architecture

Each nano-service extends `NanoService` with a single `handle(event: Event) -> None`:

1. **Subscribe** — declare interest in event types via config
2. **Dispatch** — handler wrapped with authz, idempotency, tracing, metrics, timeout
3. **Emit** — `self.emit(event)` signs with Ed25519 and publishes to the bus
4. **Persist** — state via `Store` (MemoryStore / FileStore / PostgresStore)

Cross-cutting concerns (authz, tracing, metrics, sagas, supervisor, circuit breaker) are injected by the bus and runtime — not inherited by services.

| Principle | Implementation |
|-----------|----------------|
| Event provenance | Ed25519 signature on every event, verified before dispatch |
| Fault isolation | DLQ with replay; per-subscriber circuit breaker; per-handler timeout |
| Security-first | No `str(default)` in signing; joblib gated by env var; bearer auth; PII redaction |
| RBI compliance | Per-product rate caps, all-in-cost APR, penal interest limit, KFS cooling-off |
| DPDPA compliance | Consent lifecycle, DSR fulfillment, breach notification, auto-purge |

## API

| Symbol | Type | Description |
|--------|------|-------------|
| `underwrite.Core` | ABC | Base class; implement `handle(event)` |
| `underwrite.bus` | module | Event bus — pub/sub, DLQ, rate limiter |
| `underwrite.store` | module | State store — InMemory / Disk / Sqlite |
| `underwrite.saga` | module | Saga orchestrator |
| `underwrite.authz` | module | Access control + Ed25519 verification |
| `underwrite.keypair` | module | Ed25519 key management |
| `underwrite.message` | module | 105+ event types (`Type` enum, `Message` envelope) |
| `underwrite.pii` | module | PII redaction (Aadhaar, PAN, etc.) |
| `underwrite.config` | module | Pydantic configuration (28 sections) |
| `underwrite.cli:main` | function | `underwrite` CLI entry |
| `services.*` | packages | 34 wired nano-services + 4 KYC provider clients |

## Project Structure

```
underwrite/
├── underwrite/                    # Source (90+ modules, fully typed)
│   ├── config.py                 # Pydantic configuration (28 sections)
│   ├── bus.py                    # Event bus — pub/sub, DLQ, rate limiter
│   ├── store.py                  # State store — InMemory / Disk / Sqlite
│   ├── saga.py                   # Saga orchestrator
│   ├── authz.py                  # Access control & Ed25519 verification
│   ├── keypair.py                # Ed25519 key management
│   ├── message.py                # 105+ event types (`Type` enum, `Message` envelope)
│   ├── pii.py                    # PII redaction (Aadhaar, PAN, etc.)
│   └── services/                  # 34 wired nano-services + 4 KYC provider clients
│       ├── base.py                # NanoService ABC
│       ├── mechanism/             # Delegation state machine (core)
│       ├── compliance/            # KYC/AML — PAN category, Aadhaar Verhoeff, risk score
│       ├── pricing/               # RBI caps, APR, EMI, penal interest, foreclosure
│       ├── kfs/                   # Key Fact Statement generation
│       ├── consent/               # DPDPA consent lifecycle
│       ├── dsr/                   # Data Subject Rights fulfillment
│       ├── credit_bureau/         # CIBIL/Experian/Equifax + CKYC
│       ├── razorpay/              # Payment gateway integration
│       ├── risk/                  # ML risk scoring
│       ├── fraud/                 # Fraud detection
│       ├── audit/                 # Event ledger (PII-redacted)
│       ├── npa/                   # Asset classification (SMA/NPA/DLG)
│       ├── recovery/              # Default recovery (store-backed)
│       └── ...                    # 17 more services
├── tests/                         # 58 test files, 1167 tests
└── docs/                          # 9 updated docs for Indian market
```

## Documentation Index

| Area | Documents |
|------|-----------|
| **Getting Started** | [Installation](docs/INSTALLATION.md) · [Quickstart](docs/QUICKSTART.md) (Indian scenario) · [Configuration](docs/CONFIGURATION.md) · [Env Vars](docs/ENVIRONMENT_VARIABLES.md) |
| **Architecture** | [Overview](docs/architecture.md) · [System Design](docs/SYSTEM_DESIGN.md) · [Domain Model](docs/DOMAIN_MODEL.md) · [Design Decisions](docs/DESIGN_DECISIONS.md) |
| **Development** | [Guide](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md) · [Debugging](docs/DEBUGGING.md) · [Code Style](docs/CODE_STYLE.md) · [Build](docs/BUILD.md) |
| **Operations** | [Deployment](docs/DEPLOYMENT.md) · [Operations](docs/OPERATIONS.md) · [Observability](docs/OBSERVABILITY.md) · [Security](docs/SECURITY.md) (DPDPA) · [Performance](docs/PERFORMANCE.md) |
| **Reference** | [API](docs/API.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [FAQ](docs/FAQ.md) · [Glossary](docs/GLOSSARY.md) |
| **Project** | [Contributing](docs/CONTRIBUTING.md) · [Maintenance](docs/MAINTENANCE.md) · [Roadmap](docs/ROADMAP.md) |

## Development

```bash
pip install -e ".[dev,risk,serve,postgres,otlp,vault,aws]"
pytest tests/ --tb=short -q
ruff check underwrite/
ruff format underwrite/
mypy underwrite/
bandit -r underwrite/
pip-audit
mutmut run                     # mutation testing (optional)
```

## Testing

```bash
pytest tests/ --tb=short -q
pytest tests/ -x --timeout=30
pytest --cov=underwrite --cov-report=term-missing
```

The suite contains **1167 tests** across rate limiting, idempotency, PII redaction, RBAC, saga orchestration, and Prometheus metrics.

## Build

```bash
pip install build
python -m build
```

## Release

```bash
pytest && ruff check underwrite/ && mypy underwrite/ && bandit -r underwrite/
# Bump version (setuptools_scm derives the version from git tags)
git tag vX.Y.Z && git push origin vX.Y.Z
# .github/workflows/release.yml publishes to PyPI via trusted publishing
```

## Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python ≥ 3.10 |
| Cryptography | `cryptography` (Ed25519) |
| CLI | Typer |
| Config | Pydantic |
| State store | Memory / File / Postgres (psycopg2-binary) |
| Tracing | OpenTelemetry SDK + OTLP |
| HTTP | FastAPI + Uvicorn |
| Secrets | HashiCorp Vault (hvac) |
| Cloud | boto3 (AWS), google-cloud-storage (GCS), modal |
| ML risk | NumPy, scikit-learn |
| Lint / format | ruff |
| Type check | mypy |
| Tests | pytest, pytest-asyncio, pytest-cov, hypothesis, testcontainers |
| Security | bandit, pip-audit |
| Mutation testing | mutmut |

## Roadmap

- **v0.8.x** — Current beta: 34 wired nano-services + 4 KYC provider clients, 1167 tests, Ed25519 event provenance, RBI/DPDPA-aligned defaults.
- **v0.9.0** — Planned: real PAN (NSDL/ITD) and Aadhaar (UIDAI) integrations; CKYC live lookup; CIBIL production keys.
- **v1.0.0** — Planned: video KYC; e-NACH / UPI Autopay mandate collection; full RBAC; documented DR procedures; Docker images + Helm charts.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Code of Conduct

This project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md).

## Security

Report vulnerabilities to **sachncs@gmail.com** — see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 Sachin — not legal advice. Consult a qualified attorney before deploying in a regulated environment.
