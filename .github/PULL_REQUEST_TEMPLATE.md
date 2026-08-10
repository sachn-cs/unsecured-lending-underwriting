## Summary

<!-- One-paragraph description of the change. -->

## Type of change

<!-- Check exactly one. -->

- [ ] feat (new feature)
- [ ] fix (bug fix)
- [ ] refactor (no behaviour change)
- [ ] test (test additions / fixes only)
- [ ] docs (documentation only)
- [ ] chore (tooling, deps, CI)
- [ ] ci (CI workflow only)

## Linked issues

<!-- Use `Closes #123` or `Refs #123`. -->

## Checklist

- [ ] Conventional Commits subject used in the PR title
- [ ] `ruff check underwrite/ tests/` passes locally
- [ ] `ruff format --check underwrite/ tests/` passes locally
- [ ] `mypy underwrite/` passes locally
- [ ] `mypy underwrite/ tests/` passes locally (no `ignore_errors` safety net)
- [ ] `pytest tests/ --cov=underwrite --cov-fail-under=80` passes locally
- [ ] New / changed public API documented in `docs/`
- [ ] New env vars documented in `docs/ENVIRONMENT_VARIABLES.md`
- [ ] New CLI commands / flags documented in `docs/API.md`
- [ ] New exception re-exported from both `underwrite/__init__.py` and `underwrite/__exceptions__.py`
- [ ] No `__<name>__.py` files added; no `self.__x` private attributes introduced
- [ ] Money handled as `Decimal`, not `float`
- [ ] PII redacted at every emit / log / metric boundary
- [ ] CHANGELOG.md entry added under `[Unreleased]`

## Breaking changes

<!-- If applicable, describe the migration path. -->

## Test plan

<!-- How a reviewer can verify this. Include commands, expected outputs. -->

## Screenshots / logs

<!-- If applicable. -->
