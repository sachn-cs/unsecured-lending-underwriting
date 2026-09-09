# Contributing

Thanks for your interest in Underwrite. This document is the
shortest path to a merged change. The full contributor workflow
lives in [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md); the page
below is the headline summary.

## Quick start

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate

git checkout -b feat/my-change master
# … make your change …

make lint           # ruff check
make typecheck      # mypy
make test           # pytest, coverage ≥ 80%

git commit -m "feat: …"
git push origin feat/my-change
gh pr create --base master
```

The `setup.sh` script installs the package in editable mode with the
`[dev]` extras, copies `.env.example` to `.env`, and installs
pre-commit hooks (ruff lint + format, mypy). Re-running it is safe
and idempotent.

## What we expect from a change

1. **One concern per change.** Bug fixes, refactors, and features
   each get their own branch and PR.
2. **Tests for every code change.** A bug fix must include a
   regression test. A new public symbol must include at least one
   integration test that exercises it via `Runtime`.
3. **Doc updates.** If your change touches the public API or any
   service wiring, update the relevant page in `docs/`. The mkdocs
   site builds with `mkdocs build --strict`.
5. **No surprise dependencies.** New runtime dependencies go through
   the optional extras mechanism (`[risk]`, `[serve]`, `[otlp]`,
   `[vault]`, `[aws]`, `[gcs]`, `[notify]`, `[modal]`) so the core
   install stays minimal.
6. **Conventional Commits.** Branch names use `feat/`, `fix/,
   `refactor/`, `test/`, `docs/`, `chore/`. PR titles follow
   `<type>(<scope>): <summary>` and appear in the changelog.

## Coding standards

- **Python ≥ 3.10**, type hints everywhere, PEP 585 generics
  (`list[str]` not `List[str]`) and PEP 604 unions (`X | None` not
  `Optional[X]`).
- **Linter**: `ruff check` (rules `E`, `F`, `I`, `UP`, `B`).
- **Formatter**: `ruff format` (120-column line length).
- **Type checker**: `mypy underwrite/ tests/`.
- **Docstrings**: Google style — every public API must have a
  docstring with `Args:`, `Returns:`, and (where applicable)
  `Raises:` sections.
- **Visibility**: `__private_attr` (double underscore) for
  implementation details, `@property` accessors to expose them.
- **ABCs**: Abstract base classes for every extensible interface
  (`Store`, `EventBus`, `Core`, `SecretsBackend`).

## Running the gates locally

| Gate | Command | Notes |
|------|---------|-------|
| Lint | `make lint` or `ruff check underwrite/ tests/` | 0 errors. |
| Format | `ruff format --check underwrite/ tests/` | Re-format with `ruff format`. |
| Type check | `make typecheck` or `mypy underwrite/ tests/` | Strict (suppresses only third-party stubs). |
| Security | `bandit -r underwrite/ -c pyproject.toml` | 0 high/medium findings. |
| SPDX headers | `make spdx-check` (CI) | Every source file starts with `SPDX-License-Identifier: MIT`. |
| Dependency audit | `pip-audit --skip-editable` | 0 known-vulnerable deps. |
| Tests | `make test` or `pytest tests/ -v --cov=underwrite` | ≥ 80% coverage. |
| Mutation | `mutmut run` (optional) | Catches gaps in the assertion strategy. |

All gates except mutation testing run on every push to `master` and
every pull request via `.github/workflows/ci.yml`.

## Test layout

```
tests/
├── conftest.py                # shared fixtures
├── helpers.py                 # bus / store / runtime factories
├── test_<module>.py           # one file per underwrite module
├── test_<service>.py          # one file per nano-service
└── test_<feature>.py          # cross-cutting feature tests
```

The current suite is ~1400 tests across 73 files. Add tests in
the file that mirrors the module or service you are changing.

## Project layout

```
underwrite/
├── underwrite/                # Python package
│   ├── config.py              # Pydantic configuration
│   ├── bus.py                 # Event bus protocol + LocalBus
│   ├── store.py               # State store protocol + Sqlite
│   ├── message.py             # Typed event envelope + Message.signed
│   ├── authz.py               # AccessControl + signature verification
│   ├── keypair.py             # Ed25519 key management
│   ├── runtime.py             # Runtime orchestrator
│   ├── services/              # 34 wired nano-services
│   └── …
├── tests/                     # ~1400 tests
├── docs/                      # Source markdown for sachncs.github.io/underwrite
├── examples/                  # Runnable demos (e.g. indian_lending.py)
├── mkdocs.yml                 # Site configuration
├── .github/                   # Workflows, issue templates, CODEOWNERS
├── Dockerfile                 # Multi-stage production image
├── docker-compose.yml         # Local compose with Vault + OTLP
└── pyproject.toml             # Build + dependency metadata
```

## Pull request process

1. **Fork and clone.** Fork the repo on GitHub and clone your fork.
2. **Branch from `master`.** `git checkout -b feat/<slug> master`.
3. **Make focused commits.** Use Conventional Commits for the
   subject line; the body explains *why* if it isn't obvious.
5. **Run all gates.** `make lint typecheck test` should pass
   before you push.
6. **Push and open a PR.** Target the `master` branch. Fill in the
   PR template — the "what" and "why" sections are required.
7. **Address review.** A maintainer will review within a few
   working days. Squash or rebase as requested.
8. **Merge.** PRs are merged with squash-merge by default; the
   individual commit subject becomes the changelog entry.

## Review expectations

- At least one maintainer review is required before merge.
- All CI checks (lint, typecheck, tests across Python 3.10–3.13,
  coverage ≥ 80%, security audit, SPDX check, secret scan) must
  pass.
- New code must include tests.
- Breaking changes must be clearly documented in both the PR
  description and `CHANGELOG.md`.

## Reporting bugs

Use the [bug report](https://github.com/sachncs/underwrite/issues/new?template=bug.yml)
template. Include a minimal reproducer and the output of
`python -c "import underwrite; print(underwrite.__version__)"`.

## Feature requests

Open a [feature request](https://github.com/sachncs/underwrite/issues/new?template=feature_request.yml).
Describe the use case first; the implementation follows. Features
that are out of scope for the project (see `docs/ROADMAP.md`) will
be politely declined with a redirect to a fork.

## Security

Vulnerabilities should be reported via the
[security policy](https://github.com/sachncs/underwrite/security/policy) —
not through public issues. For sensitive findings, email
`sachncs@gmail.com` directly. See [`SECURITY.md`](SECURITY.md).

## Code of conduct

This project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md).
By participating you agree to its terms.

## License

By contributing, you agree that your contributions will be licensed
under the [MIT License](LICENSE).

## Questions?

Open a [discussion](https://github.com/sachncs/underwrite/discussions)
or file an [issue](https://github.com/sachncs/underwrite/issues).