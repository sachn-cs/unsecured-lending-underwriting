<p align="center">
  <a href="https://sachncs.github.io/underwrite/">
    <img src="https://raw.githubusercontent.com/sachncs/underwrite/master/docs/assets/branding/logo-128.png" alt="Underwrite" width="96" height="96">
  </a>
</p>

<h1 align="center">Underwrite</h1>

<p align="center">
  <strong>Event-driven nano-service platform for Indian retail lending.</strong>
  <br>
  RBI Digital Lending Guidelines + DPDPA 2023 aligned. 34 nano-services. Ed25519 cryptographic attestation.
</p>

<p align="center">
  <a href="#install"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://github.com/sachncs/underwrite/actions"><img src="https://img.shields.io/github/actions/workflow/status/sachncs/underwrite/ci.yml?branch=master" alt="CI"></a>
  <a href="https://github.com/sachncs/underwrite/blob/master/docs/"><img src="https://img.shields.io/badge/docs-sachncs.github.io%2Funderwrite-blue" alt="Documentation"></a>
  <a href="https://github.com/sachncs/underwrite/stargazers"><img src="https://img.shields.io/github/stars/sachncs/underwrite" alt="Stars"></a>
</p>

---

## Install

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate
pytest tests/ -q   # ~1276 tests across 72 test files
```

Or, if you already use Python 3.10+ and want to consume Underwrite as a library from this checkout:

```bash
pip install -e ".[dev,risk,serve,otlp,vault,aws]"
```

> **Pre-release status.** The first public PyPI release has not been published yet, so `pip install underwrite` will fail until the `v0.9.0` tag lands. Until then, install from source as shown above. Track release readiness in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## What Underwrite does

Underwrite is a **nano-service platform** for delegated underwriting of unsecured retail loans in India. Each domain boundary is a small `Core` subclass that emits and consumes typed, Ed25519-signed events on an in-process bus. Cross-cutting concerns — authz, tracing, metrics, idempotency, sagas, DLQ, circuit breaking — are injected by the runtime, not inherited.

| Pillar | What you get |
|--------|--------------|
| **Domain coverage** | 34 wired nano-services plus 4 KYC provider clients — KYC/AML, CIBIL/CKYC, RBI pricing, KFS, DPDPA consent + DSR, Razorpay PG, risk scoring, fraud detection, collections, recovery, notifications, governance |
| **Compliance by default** | Per-product rate caps, all-in-cost APR, penal-interest cap, KFS cooling-off, consent lifecycle, DSR fulfillment, breach notification, auto-purge |
| **Provable event history** | Ed25519 signature on every event, 5-minute replay window, PII-redacted audit, DLQ with bounded memory, optional store-backed DLQ |
| **Pluggable backends** | Sqlite store (file or `:memory:`); local in-process bus; console / OTLP tracing; env / Vault / AWS secrets |

## At a glance

```bash
underwrite init                 # create underwrite.json
underwrite run mechanism audit  # start any subset of the 34 services
python docs/examples/indian_lending.py   # simulate a full RBI-aligned loan lifecycle
underwrite health               # system health
underwrite dlq [--replay]       # inspect or replay dead-lettered events
underwrite metrics              # Prometheus-format snapshot
```

A complete walkthrough — config, lifecycle events, audit trail — lives in [docs/QUICKSTART.md](docs/QUICKSTART.md).

## Quick architecture tour

```
underwrite/
├── underwrite/                  # Source (90+ modules, fully typed)
│   ├── config.py                # Pydantic configuration (28 sections)
│   ├── bus.py                   # Event bus — pub/sub, DLQ, rate limiter
│   ├── store.py                 # State store — Sqlite (file path or :memory:)
│   ├── saga.py                  # Saga orchestrator
│   ├── authz.py                 # Access control & Ed25519 verification
│   ├── keypair.py               # Ed25519 key management
│   ├── message.py               # 132 event types (`Type` enum, `Message` envelope)
│   ├── pii.py                   # PII redaction (Aadhaar, PAN, etc.)
│   └── services/                # 34 wired nano-services + 4 KYC provider clients
│       ├── base.py              # `Core` ABC
│       ├── mechanism/           # Delegation state machine
│       ├── compliance/          # KYC/AML — PAN category, Aadhaar Verhoeff
│       ├── pricing/             # RBI caps, APR, EMI, penal interest
│       ├── kfs/                 # Key Fact Statement
│       ├── consent/             # DPDPA consent lifecycle
│       ├── dsr/                 # Data Subject Rights fulfillment
│       ├── credit_bureau/       # CIBIL/Experian/Equifax + CKYC
│       ├── razorpay/            # Payment gateway integration
│       ├── risk/                # ML risk scoring
│       ├── fraud/               # Fraud detection
│       ├── audit/               # Event ledger (PII-redacted)
│       ├── npa/                 # Asset classification (SMA/NPA/DLG)
│       ├── recovery/            # Default recovery (store-backed)
│       └── ...                  # 17 more services
├── tests/                       # 72 test files
├── docs/                        # Full documentation (rendered at sachncs.github.io/underwrite)
└── examples/                    # indian_lending.py walkthrough
```

The architectural decisions behind this layout are captured as ADRs in [`docs/ADR/`](docs/ADR/README.md).

## Service map

The 34 wired services are listed below with the events they emit and consume.

| Service | Emits | Consumes |
|---------|-------|----------|
| `mechanism` | `seed.added`, `user.added`, `loan.originated`, `loan.drawn`, `loan.repaid`, `loan.defaulted` | `command` events from `mechanism` |
| `audit` | `audit.appended` | every event type (mirror) |
| `risk` | `risk.scored` | `loan.application.received` |
| `fraud` | `fraud.alert` | `loan.application.received`, `loan.originated` |
| `compliance` | `kyc.verified`, `aml.cleared`, `ckyc.verify` | `kyc.check` commands |
| `pricing` | `pricing.computed` | `pricing.compute` commands |
| `kfs` | `kfs.generated` | `kfs.generate` commands |
| `consent` | `consent.recorded`, `consent.withdrawn` | `consent.record` / `consent.withdraw` |
| `dsr` | `dsr.fulfilled`, `dsr.rejected` | `dsr.request` |
| `credit_bureau` | `credit_bureau.checked` | `credit_bureau.check` |
| `razorpay` | `payment.captured`, `refund.processed` | `payment.create`, `refund.create` |
| `underwriter` | `underwriter.approved`, `underwriter.rejected` | `underwriter.evaluate` |
| `decision` | `decision.made` | `decision.request` |
| `npa`, `collateral`, `recovery`, `reporting`, `notification`, `governance`, `graph`, `identity`, `pricing` *(see code)*, `document`, `disbursement`, `collection`, `settlement`, `origination`, `servicing`, `payment`, `communication`, `workflow`, `fee`, `statement`, `prepayment` | per service wiring |

The full event-to-service wiring lives in [`underwrite/handler.py`](underwrite/handler.py).

## CLI reference

```
underwrite

Commands:
  init [PATH]              Create default config
  run <service>...         Start one or more services
  list                     List all wired nano-services
  identity <service>       Generate Ed25519 keypair
  health                   System health status
  dlq [--replay] [--max N] Show or replay dead-letter queue
  metrics                  Metrics snapshot (Prometheus-format on /v1/metrics)
  migrate                  Run pending schema migrations
  serve                    Start HTTP daemon (requires the [serve] extra)
```

### HTTP API (with `underwrite serve`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz` | GET | Liveness probe |
| `/readyz` | GET | Readiness probe |
| `/v1/health` | GET | Full system health |
| `/v1/metrics` | GET | Prometheus-format metrics |
| `/v1/publish` | POST | Publish a domain event |

Authentication uses `Authorization: Bearer <token>` when started with `--require-auth`.

## Configuration

Configure through **JSON file** (created with `underwrite init`), **env vars**, or both (env vars override). See [`.env.example`](.env.example) for the full set of variables, including RBI pricing caps, AML thresholds, credit-bureau API keys, Razorpay credentials, and DPDPA retention periods.

| Setting | Env variable | Default | Description |
|---------|--------------|---------|-------------|
| State backend | `UNDERWRITE_STORE_BACKEND` | `sqlite` | `sqlite` / `memory` |
| Store path | `UNDERWRITE_STORE_PATH` | `./store.db` | Sqlite path (use `:memory:` for ephemeral) |
| Personal-loan rate cap | `UNDERWRITE_PERSONAL_LOAN_RATE_CAP` | `0.28` | RBI cap |
| Penal-interest cap | `UNDERWRITE_PENAL_INTEREST_CAP` | `0.24` | RBI cap |
| Bearer auth | `UNDERWRITE_REQUIRE_AUTH` | `false` | Require bearer token on `/v1/*` |

The full configuration surface — 28 sections, ~120 keys — is documented in [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Architecture principles

| Principle | Implementation |
|-----------|----------------|
| Event provenance | Ed25519 signature on every event, verified before dispatch |
| Fault isolation | DLQ with replay; per-subscriber circuit breaker; per-handler timeout |
| Security-first | No `default=str` in signing; joblib gated by env var; bearer auth; PII redaction |
| RBI compliance | Per-product rate caps, all-in-cost APR, penal-interest limit, KFS cooling-off |
| DPDPA compliance | Consent lifecycle, DSR fulfillment, breach notification, auto-purge |

The full architectural decision log lives in [`docs/ADR/`](docs/ADR/README.md).

## Public API surface

| Symbol | Type | Description |
|--------|------|-------------|
| `underwrite.Core` | ABC | Base class; implement `handle(event)` |
| `underwrite.bus` | module | Event bus — pub/sub, DLQ, rate limiter |
| `underwrite.store` | module | State store — Sqlite (file path or `:memory:`) |
| `underwrite.saga` | module | Saga orchestrator |
| `underwrite.authz` | module | Access control + Ed25519 verification |
| `underwrite.keypair` | module | Ed25519 key management |
| `underwrite.message` | module | 132 event types (`Type` enum, `Message` envelope) |
| `underwrite.pii` | module | PII redaction (Aadhaar, PAN, etc.) |
| `underwrite.config` | module | Pydantic configuration (28 sections) |
| `underwrite.cli:main` | function | `underwrite` CLI entry point |
| `underwrite.services.*` | package | 34 wired nano-services + 4 KYC provider clients |

A full reference — every public symbol, parameter, and return type — is rendered at [sachncs.github.io/underwrite/reference/](https://sachncs.github.io/underwrite/reference/) and is also browsable as [`docs/API.md`](docs/API.md).

## Documentation

Full documentation is published at **<https://sachncs.github.io/underwrite/>**.

| Area | Documents |
|------|-----------|
| **Getting started** | [Installation](docs/INSTALLATION.md) · [Quickstart](docs/QUICKSTART.md) (Indian scenario) · [Configuration](docs/CONFIGURATION.md) · [Env vars](docs/ENVIRONMENT_VARIABLES.md) |
| **Architecture** | [Overview](docs/architecture.md) · [System design](docs/SYSTEM_DESIGN.md) · [Domain model](docs/DOMAIN_MODEL.md) · [Design decisions](docs/DESIGN_DECISIONS.md) · [Directory structure](docs/DIRECTORY_STRUCTURE.md) |
| **Development** | [Guide](docs/DEVELOPMENT.md) · [Testing](docs/TESTING.md) · [Debugging](docs/DEBUGGING.md) · [Code style](docs/CODE_STYLE.md) · [Build](docs/BUILD.md) · [Contributing](docs/CONTRIBUTING.md) |
| **Operations** | [Deployment](docs/DEPLOYMENT.md) · [Operations](docs/OPERATIONS.md) · [Observability](docs/OBSERVABILITY.md) · [Security](docs/SECURITY.md) (DPDPA) · [Performance](docs/PERFORMANCE.md) |
| **Reference** | [API](docs/API.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [FAQ](docs/FAQ.md) · [Glossary](docs/GLOSSARY.md) · [Dependencies](docs/DEPENDENCIES.md) |

## Development

```bash
pip install -e ".[dev,risk,serve,otlp,vault,aws]"
pytest tests/ --tb=short -q
ruff check underwrite/
ruff format underwrite/
mypy underwrite/
bandit -r underwrite/
pip-audit
mutmut run                # mutation testing (optional)
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) and [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the full contributor workflow.

## Testing

```bash
pytest tests/ --tb=short -q          # ~1276 tests, 72 test files
pytest tests/ -x --timeout=30        # fail fast, with per-test timeout
pytest --cov=underwrite --cov-report=term-missing
```

Coverage is enforced at 80% in CI.

## Build and release

```bash
pip install build
python -m build
```

Tag-driven publishing happens through `.github/workflows/release.yml`:

```bash
pytest && ruff check underwrite/ && mypy underwrite/ && bandit -r underwrite/
# Bump version (setuptools_scm derives the version from git tags)
git tag vX.Y.Z && git push origin vX.Y.Z
```

## Tech stack

| Category | Technology |
|----------|------------|
| Language | Python ≥ 3.10 |
| Cryptography | `cryptography` (Ed25519) |
| CLI | Typer |
| Config | Pydantic v2 |
| State store | Sqlite (stdlib `sqlite3`) |
| Tracing | OpenTelemetry SDK + OTLP |
| HTTP | FastAPI + Uvicorn |
| Secrets | HashiCorp Vault (`hvac`) |
| Cloud | `boto3` (AWS), `google-cloud-storage` (GCS), Modal |
| ML risk | NumPy, scikit-learn |
| Lint / format | ruff |
| Type check | mypy |
| Tests | pytest, pytest-asyncio, pytest-cov, hypothesis |
| Security | bandit, pip-audit |
| Mutation testing | mutmut |

## Roadmap

The current target is the **v1.0** line, with the v0.9 hardening pass landed. v1.0 brings live KYC partner-sandbox validation, e-NACH / UPI Autopay mandate collection, full RBAC, a production on-call runbook, and pre-built multi-arch Docker images. A Helm chart is **not** planned. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). New services require tests, ADRs for material design decisions, and an updated entry in [docs/SERVICES.md](docs/SERVICES.md).

## Code of conduct

This project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md).

## Security

Report vulnerabilities to **sachncs@gmail.com** — see [SECURITY.md](SECURITY.md).

## Support

For usage questions, see [SUPPORT.md](SUPPORT.md). For bug reports, [open an issue](https://github.com/sachncs/underwrite/issues/new?template=bug.yml).

## License

[MIT](LICENSE) © 2026 Sachin — not legal advice. Consult a qualified attorney before deploying in a regulated environment.