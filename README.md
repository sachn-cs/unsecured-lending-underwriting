# Unsecured Lending via Delegated Underwriting (ULU)

Pure-Python implementation of arXiv:2605.03307v1.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
pip install -e ".[dev]"
```

## Run demo

```bash
PYTHONPATH=. python demo.py run-demo
PYTHONPATH=. python demo.py run-demo --state-path ./state.json
```

## Run API

```bash
pip install -e ".[api]"
uvicorn ulu.api:app --host 0.0.0.0 --port 8000
```

## Ops endpoints

- `GET /health` liveness
- `GET /ready` invariant-checked readiness
- `GET /metrics` Prometheus plaintext metrics
- `GET /admin/graph` graph inspection
- `GET /admin/solvency` solvency inspection
- `GET /admin/utilization` utilization inspection
- `POST /admin/reset` runtime reset

Mutation endpoints support optional `Idempotency-Key` header.
See `RUNBOOK.md` for operational procedures.

## Risk model estimation (`D_v`)

Latest integrated paper source:
- https://arxiv.org/abs/2603.18927

Implemented module:
- `ulu.risk_model.OptimizedGreedyWeightedRiskModel`

Install risk dependencies:
```bash
pip install -e ".[risk]"
```

## Run tests

```bash
PYTHONPATH=. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```

## Quality checks

```bash
ruff check ulu/ tests/ demo.py
```

## Documentation

- `FIDELITY_REPORT.md`: theorem/definition-level fidelity status.
- `GAP_ANALYSIS.md`: what was missing/partial and what was fixed.
- `PRODUCTION_READINESS.md`: operational hardening summary.
- `docs/setup.md`: environment setup.
- `docs/running.md`: running the simulator and API.
- `docs/revocation.md`: revocation rules and solvency.
- `docs/default.md`: default propagation logic.
- `docs/pricing.md`: protocol and delegation premium formulas.
- `docs/theorems.md`: theorem evaluation and test references.
- `docs/extensions.md`: review of possible extensions.

## Scope and assumptions

- Source of truth: arXiv e-print TeX for `2605.03307v1`.
- Runtime dependency footprint: `loguru` plus optional `api`/`risk` extras.
- One active loan per borrower at origination (`x_u = 0` precondition).
- Default probability estimation `D_v` is exogenous per paper.
