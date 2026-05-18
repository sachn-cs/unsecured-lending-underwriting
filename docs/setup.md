# Setup

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Dev dependencies

```bash
pip install -e ".[dev]"
```

## Optional extras

- `api` — FastAPI server (`pip install -e ".[api]"`)
- `risk` — ML risk-model estimation (`pip install -e ".[risk]"`)

## Verify

```bash
PYTHONPATH=. pytest -q
```
