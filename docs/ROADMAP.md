# Roadmap

Based on `docs/REFACTORING_PLAN.md` and codebase analysis.

---

## v0.9 — hardening + real KYC integrations (landed)

The v0.9 release line replaces the protocol-stub KYC providers
with full wire-protocol clients (Karza-style / UIDAI KUA / CIBIL
partner / CERSAI), the production Dockerfile ships a multi-stage
build with non-root user and healthcheck, and the docs / changelog
reflect the hardened state. See `CHANGELOG.md` for the full
list of fixes.

- Real PAN verification client (`services/providers.pypan.py`)
- Real Aadhaar eKYC client (`services/providers.pyaadhaar.py`)
- Real CIBIL consumer bureau pull (`services/providers.pycibil.py`)
- Real CKYC registry search (`services/providers.pyckyc.py`)
- Common `KycProvider` ABC + `Verdict` enum + `ProviderResult`
  envelope (`services/providers.pybase.py`)
- Runtime auto-wires the configured providers into the
  compliance and credit-bureau services
- Production Dockerfile (`Dockerfile`) — multi-stage, non-root,
  healthcheck, OCI labels, build args
- Docker image CI workflow (`.github/workflows/docker.yml`)
- PyPI release workflow (`.github/workflows/release.yml`)
- `scripts/build-image.sh` — local build helper

### Out of scope (declared, not planned)

The following items are explicitly **not** on the roadmap. The
maintainer does not intend to ship them; downstream operators
are expected to integrate their own equivalent.

- **Helm chart for Kubernetes** — not planned. Deploy the
  multi-arch container directly, or with a project-specific
  compose / kustomize overlay.

---

## v1.0 — production hardening

Target: ship a v1.0 release with full operator runbook, live
partner-sandbox validation, and pre-built multi-arch images.
Estimated effort: 4-6 weeks.

| Priority | Item | Est. |
|----------|------|------|
| Critical | Run the v0.9 image against a real KYC sandbox end-to-end (Karza, UIDAI KUA, CIBIL partner, CERSAI) | 1w |
| Critical | Pin partner sandbox URLs and capture operator documentation | 2d |
| Critical | Add provider sandbox tests in CI (mock the partner sandbox) | 2d |
| Critical | Wire Razorpay e-NACH / UPI Autopay mandate collection | 3d |
| Critical | Pre-built multi-arch (amd64 + arm64) images published to GHCR | 2d |
| Critical | Production on-call runbook (incident response, Ed25519 key rotation, DLQ replay, breach notification) | 1w |
| High | Full RBAC beyond the basic policy-file allow/deny engine (per-user / per-role, with secret-manager-backed credential issuance) | 1w |
| High | Video KYC provider integration (Digilocker, NSDL eSign) | 2w |
| High | Read-only `underwrite` role for `psql` / Vault operations | 1d |
| Medium | OpenAPI 3.1 spec generated from the FastAPI surface | 2d |
| Medium | Saga persistence via Store backend (in-memory only today) | 3-4h |
| Medium | Prometheus `/metrics` endpoint at standard path | 2h |
| Medium | Async event bus (`asyncio`) implementation | 4-6h |
| Medium | Configuration validation at Runtime startup (not just load) | 1h |
| Low | MeitY-empanelled cloud provider deployment guide | 1d |
| Low | Structured audit export to S3/GCS | 4h |
| Low | JSON Schema enforcement at runtime | 2h |

---

## Medium-term — v0.3.0 / v0.4.0

| Priority | Item | Est. |
|----------|------|------|
| High | RBI monthly/quarterly reporting auto-generation | 2d |
| High | FastAPI OTLP auto-instrumentation | 2h |
| High | RBI audit trail export (XBRL format for regulatory filings) | 2d |
| Medium | Config-driven fee schedules (replace `FEE_SCHEDULES` module-level dict) | 2h |
| Medium | Plugin-based model loading (strategy pattern for risk models) | 3h |
| Medium | Distributed rate limiting (with Store backend) | 2h |
| Medium | DLQ persistence + replay automation (CLI command) | 2h |
| Low | Indian language document generation (Hindi, Marathi, Tamil) | 2d |
| Low | `tox.ini` for local matrix testing | 30m |

---

## Production Readiness — v1.0.0

Target: **80+ production readiness score** (currently 57/100).

| Category | Target | Current |
|----------|--------|---------|
| Architecture | 85+ | 75 |
| Security | 80+ | 45 |
| Testing | 80+ | 70 |
| Performance | 70+ | 40 |
| Observability | 80+ | 35 |
| Packaging | 80+ | 60 |
| Documentation | 70+ | 40 |
| DevOps | 70+ | 30 |
| Developer Experience | 70+ | 50 |

### Must-have for v1.0.0
- Fix all critical security issues (token exposure, path traversal, SQL injection)
- Prometheus `/metrics` at standard path (`GET /metrics`, not `/v1/metrics`)
- Structured logging with correlation IDs
- Async event bus
- Saga persistence (not in-memory)
- Distributed event bus support (SQS/Modal) — at least one production backend
- Pre-commit hooks configured
- `docker-compose.yml` for local Postgres + Vault + OTLP
- 80%+ test coverage with concurrency stress tests

### Nice-to-have for v1.0.0
- Config-driven fee schedules
- Plugin-based model loading
- Structured audit export to object storage
- PyPI publishing CI
