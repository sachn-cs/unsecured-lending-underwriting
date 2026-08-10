# Build and Packaging

## Build Wheel and Source Distribution

```bash
python -m build
```

Output is written to `dist/`:

```
dist/
├── underwrite-0.1.dev65+gad81577c8.tar.gz   # sdist
└── underwrite-0.1.dev65+gad81577c8-py3-none-any.whl  # wheel
```

The build system uses `setuptools` with `setuptools-scm` for versioning. No `version` field is hardcoded in `pyproject.toml` — it is declared `dynamic = ["version"]`.

## Versioning

Version strings are derived from git tags by `setuptools-scm`. The resolved version is written to `underwrite/__version__.py` at build time:

```python
__version__ = version = "0.1.dev65+gad81577c8.d20260608"
```

This file is git-ignored and regenerated on every build.

Tag a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Docker Build

The `Dockerfile` uses a multi-stage build:

```
python:3.12-slim (builder)  →  python:3.12-slim (runtime)
```

- **Builder**: installs build deps, builds the wheel, installs it with `[serve,postgres,otlp]` extras
- **Runtime**: copies only installed site-packages and the `underwrite` binary, creates a non-root `underwrite` user (uid 1001), exposes port 8080, and runs `underwrite serve --host 0.0.0.0 --port 8080`

Build:

```bash
docker build -t underwrite .
```

The `.dockerignore` excludes `.git/`, `.venv/`, `tests/`, `__pycache__/`, build artifacts, and `.env` to keep the image lean.

## CI Build

Defined in `.github/workflows/ci.yml`:

- **lint job**: Python 3.12 — install with `[dev,risk,serve,postgres,otlp,vault,aws]` extras, then run ruff, mypy, bandit, pip-audit, and pytest
- **docker job**: Python 3.12 — build the Docker image, run a container in background, curl `/healthz` as a smoke test, then stop the container

## Dependencies

All dependencies are declared exclusively in `pyproject.toml`:

- **Core** (`dependencies`): `cryptography>=41.0`, `typer>=0.12`, `pydantic>=2.0`
- **Optional extras**: each extra is a list under `[project.optional-dependencies]`

There is no `requirements.txt` or `requirements-dev.txt`. The project uses `setuptools` for runtime packaging and pip for dependency resolution.

## Publishing

Editable install for local development:

```bash
pip install -e ".[dev]"
```

For production deployment, install from the built wheel or from PyPI:

```bash
pip install underwrite[serve,postgres]
```

To publish to PyPI (requires PyPI credentials):

```bash
python -m build
twine check dist/*.whl dist/*.tar.gz
twine upload dist/*
```
