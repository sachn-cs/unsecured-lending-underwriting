# Changelog Guide

This document describes the changelog format used for the underwrite project. All changelog entries must follow these conventions.

## Format

underwrite uses the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) standard.

Each release is documented in `CHANGELOG.md` at the repository root.

## Sections

Entries are grouped under the following section headers, in this order:

| Section    | Purpose                                              |
|------------|------------------------------------------------------|
| **Added**  | New features, services, modules, endpoints           |
| **Changed**| Changes to existing functionality, refactors         |
| **Fixed**  | Bug fixes                                            |
| **Security** | Vulnerability fixes, security hardening            |
| **Removed**  | Deprecated features removed                        |

If a section has no entries for a given release, omit it entirely.

## Unreleased Section

All unreleased changes live under `## [Unreleased]` at the top of the file. When a release is cut, the `[Unreleased]` section is recreated empty and the current contents are moved to a dated version header.

```markdown
## [Unreleased]

### Added
- (new items here)

### Changed
- (changed items here)
```

## Conventional Commits Alignment

Changelog entries should align with Conventional Commits prefixes used in the repo:

| Commit type  | Changelog section | Example                                  |
|--------------|-------------------|------------------------------------------|
| `feat:`      | Added             | `feat: add OTLP auto-instrumentation`    |
| `fix:`       | Fixed             | `fix: handle corrupted audit JSONL lines`|
| `refactor:`  | Changed           | `refactor: extract store validation`     |
| `perf:`      | Changed           | `perf: reduce serialization overhead`    |
| `security:`  | Security          | `security: redact PII in JSON logs`      |
| `test:`      | (no entry)        | —                                        |
| `docs:`      | (no entry)        | —                                        |
| `chore:`     | (no entry)        | —                                        |
| `ci:`        | (no entry)        | —                                        |

- `docs:` changes typically do not warrant a changelog entry unless they represent a significant documentation milestone.
- Multiple related commits can be consolidated into a single changelog entry.

## Version Headers

```markdown
## [X.Y.Z] - YYYY-MM-DD
```

Examples:
```markdown
## [Unreleased]

## [0.1.0] - 2026-06-08

## [0.1.0-alpha] - 2026-06-01
```

- Use ISO 8601 date format (`YYYY-MM-DD`).
- Pre-release versions use the exact tag name as the header.

## Entry Style

Each entry is a bullet point starting with a capital letter, ending without a period (unless it contains multiple sentences). Be specific and reference the component or file where relevant:

```markdown
### Added
- Event payload size validation — payloads exceeding 1 MB raise `ProtocolError`
- Per-handler timeout (30s) in `AsyncLocalBus` — slow handlers are sent to DLQ
- Distributed tracing context propagation — `trace_id` and `parent_span_id` fields on `Event`

### Changed
- `import random` moved from method body to module level in `circuit.py`
- British English → American English in all docstrings (`Initialises` → `Initializes`)

### Fixed
- Async bus DLQ persistence — `AsyncLocalBus` now passes store to `DeadLetterQueue`
- Async dispatch loop handles `CancelledError` for clean shutdown
```

Use backticks for identifiers (method names, class names, file paths, config keys).

## Breaking Changes

Breaking changes must be clearly marked. Use a `### Breaking Changes` subsection within the relevant section, or prefix the entry with **[BREAKING]**:

```markdown
### Changed
- **BREAKING**: `Configuration.to_dict()` no longer serializes `token` field
- **BREAKING**: `ServeConfig` now requires `host` and `port` as keyword-only arguments
```

Alternatively, use a dedicated paragraph before the changed list.

## Linking

Link to issues, commits, or pull requests where helpful:

```markdown
### Fixed
- Path traversal bypass in `FileStore.__path` — see [#42](https://github.com/sachncs/underwrite/issues/42)
- NaN/Inf propagation in `FeeService` — fixed in `a1b2c3d`
```

Repository URLs use: `https://github.com/sachncs/underwrite`

## Example (from existing CHANGELOG.md)

```markdown
## [Unreleased]

### Added
- Event payload size validation — payloads exceeding 1 MB raise `ProtocolError`
- Per-handler timeout (30s) in `AsyncLocalBus` — slow handlers are sent to DLQ
- Distributed tracing context propagation — `trace_id` and `parent_span_id` fields on `Event`

### Changed
- `import random` moved from method body to module level in `circuit.py`
- British English → American English in all docstrings (`Initialises` → `Initializes`)

### Fixed
- Async bus DLQ persistence — `AsyncLocalBus` now passes store to `DeadLetterQueue`

### Security
- Production guardrail warning when `cryptography` library is not installed
- All sensitive field values (passwords, tokens, SSNs, etc.) are redacted in JSON logs
```

## Release Checklist

When preparing a release:

1. Review all commits since the last release tag.
2. Group commits into changelog sections by type.
3. Rewrite commit messages into readable prose entries.
4. Create the version header with today's date.
5. Reset the `[Unreleased]` section to empty.
6. Commit as `chore: prepare vX.Y.Z`.
7. Tag and proceed with the [release process](RELEASE_PROCESS.md).

## Automation

The changelog is maintained manually rather than auto-generated, to ensure each entry is written in a consistent, human-readable voice. Contributors are encouraged to update `CHANGELOG.md` as part of their pull requests when their change has user-visible impact.
