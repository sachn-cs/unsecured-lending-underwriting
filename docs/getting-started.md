# Getting started

This page is the shortest path from a clean checkout to a running
Underwrite runtime with your first event flowing through the bus. It
is intentionally short; the rest of the documentation is here for
depth.

!!! tip "Already familiar with event-driven systems?"
    Jump straight to [Build your first service](TUTORIAL_FIRST_SERVICE.md) or
    [Tutorial: the event bus](TUTORIAL_EVENT_BUS.md).

## Prerequisites

- **Python 3.10+** with `pip` and `git` on `PATH`.
- A POSIX shell (Linux, macOS, or WSL). Windows works in WSL; native
  Windows shells are not exercised by the test suite.

## Install

Clone the repo and use the bundled setup script. It is idempotent and
safe to re-run.

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate
```

The script:

1. Verifies Python ≥ 3.10, `pip`, and `git`.
2. Creates a `.venv` virtual environment.
3. Upgrades `pip`, `setuptools`, and `wheel`.
4. Installs the package in editable mode with `[dev]` extras
   (pytest, ruff, mypy, bandit, pip-audit, hypothesis).
5. Installs pre-commit hooks (ruff lint + format, mypy).
6. Copies `.env.example` to `.env` if not present.
7. Validates the environment (import check, version, tool availability).

To install a different extras profile instead — say you only need the
HTTP server and ML risk models — run the manual path:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,risk,serve]"
```

See [Installation](INSTALLATION.md) for the full extras reference.

## Verify

```bash
python -c "import underwrite; print(underwrite.__version__)"
pytest tests/ -q
```

The test summary should report ~1276 passed. If you see fewer, run
with `-vv` and open an issue with the failure trace.

## Run the demo

The bundled demo exercises a full RBI-aligned origination against an
in-memory runtime:

```bash
underwrite init
python docs/examples/indian_lending.py
```

You should see events flowing through the bus, the audit trail
populating, and `health` and `dlq` snapshots at the end.

The annotated walkthrough lives in [Quickstart](QUICKSTART.md).

## Start the HTTP daemon

```bash
pip install -e ".[serve]"
underwrite serve
```

The daemon exposes:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/healthz` | GET | Liveness probe (cheap, never rate-limited). |
| `/readyz` | GET | Readiness probe — pings the store. |
| `/v1/health` | GET | Full subsystem health. |
| `/v1/metrics` | GET | Prometheus-format metrics. |
| `/v1/publish` | POST | Publish a domain event. |

Auth is off by default. Enable it with
`--require-auth` and set `UNDERWRITE_API_TOKEN`:

```bash
underwrite serve --require-auth
UNDERWRITE_API_TOKEN="$(openssl rand -hex 32)" underwrite serve
```

Then call any `/v1/*` endpoint with
`Authorization: Bearer $UNDERWRITE_API_TOKEN`.

## Where to go next

- [Build your first service](TUTORIAL_FIRST_SERVICE.md) — write a
  nano-service in under 50 lines and watch it handle an event.
- [Tutorial: the event bus](TUTORIAL_EVENT_BUS.md) — see how
  publish, subscribe, authz, idempotency, and DLQ interact.
- [Tutorial: custom nano-services](TUTORIAL_CUSTOM_NANO.md) — the
  patterns used by the 34 wired services, distilled.
- [Tutorial: pluggable backends](TUTORIAL_PLUGINS.md) — swap the
  store, the bus, the secrets manager, or the tracer.
- [Architecture](architecture.md) — diagrams and decisions.
- [API reference](reference.md) — every public symbol.
- [Development guide](DEVELOPMENT.md) — dev loop, testing, debugging.