# Roadmap

The roadmap is split into **shipped**, **next**, and **not planned**.
Shipped items stay in the changelog (`CHANGELOG.md`); they are removed
from this file so the document only describes what is still ahead.

---

## Shipped — v0.9 hardening

The v0.9 line is the current release series. It replaced the
protocol-stub KYC providers with full wire-protocol clients (PAN, Aadhaar
eKYC, CIBIL, CKYC), shipped the production multi-stage Dockerfile with
a non-root user and healthcheck, and tightened every CI gate.

- Real PAN, Aadhaar eKYC, CIBIL, and CKYC wire-protocol clients in `underwrite/services/providers.py`
- Common `KycProvider` ABC + `Verdict` enum + `ProviderResult` envelope
- Runtime auto-wires the configured providers into compliance and credit-bureau services
- Production `Dockerfile` — multi-stage, non-root, healthcheck, OCI labels, build args
- Docker image CI workflow (`.github/workflows/docker.yml`)
- PyPI release workflow (`.github/workflows/release.yml`)
- `scripts/build-image.sh` — local build helper
- Ed25519 event signatures, 5-minute replay window, `SecretsManager`-backed private keys
- `/v1/publish` binds the publisher identity from the request payload with an optional authz gate
- PII redacted at the audit, DLQ, and Prometheus tag boundaries
- DLQ, bus buffer, idempotency guard all bounded against unbounded memory growth
- Indian holiday calendar covers 2025–2030 with a sensible fallback
- KFS APR math, pricing EMI, NPA thresholds, and the underwriter rule engine aligned with RBI norms

The full release notes live in [`CHANGELOG.md`](../CHANGELOG.md).

---

## Next — v1.0

Target: a v1.0 release with a documented on-call runbook, live
partner-sandbox validation, and pre-built multi-arch images. ETA is
tracked per-item below; nothing in this section is blocked on a
single piece of upstream work.

| Priority | Item | Est. effort |
|----------|------|-------------|
| Critical | Run the v0.9 image against a real KYC sandbox end-to-end (PAN, Aadhaar, CIBIL, CKYC) | 1 week |
| Critical | Pin partner sandbox URLs and capture operator documentation | 2 days |
| Critical | Add provider sandbox tests in CI (mock the partner sandbox) | 2 days |
| Critical | Wire Razorpay e-NACH / UPI Autopay mandate collection | 3 days |
| Critical | Pre-built multi-arch (amd64 + arm64) images published to GHCR | 2 days |
| Critical | Production on-call runbook (incident response, Ed25519 key rotation, DLQ replay, breach notification) | 1 week |
| High | Full RBAC beyond the basic policy-file allow/deny engine | 1 week |
| High | Video KYC provider integration (Digilocker, NSDL eSign) | 2 weeks |
| High | Read-only `underwrite` role for `psql` / Vault operations | 1 day |
| Medium | OpenAPI 3.1 spec generated from the FastAPI surface | 2 days |
| Medium | Saga persistence via the Store backend (currently in-memory only) | 3–4 hours |
| Medium | Prometheus `/metrics` endpoint at the standard path (currently `/v1/metrics`) | 2 hours |
| Medium | Async event bus (`asyncio`) implementation | 4–6 hours |
| Medium | Configuration validation at Runtime startup (not just `load`) | 1 hour |
| Low | MeitY-empanelled cloud provider deployment guide | 1 day |
| Low | Structured audit export to S3/GCS | 4 hours |
| Low | JSON Schema enforcement at runtime | 2 hours |

---

## Not planned

The following items are explicitly **not** on the roadmap. The
maintainer does not intend to ship them; downstream operators are
expected to integrate their own equivalent.

- **Helm chart for Kubernetes.** Deploy the multi-arch container
  directly, or with a project-specific compose / kustomize overlay.
  This decision is final; please do not open feature requests for it.
- **Multi-tenant serverless runtime.** Underwrite is a single-tenant
  per-process runtime. SaaS multi-tenancy should be layered
  upstream by an orchestrator.
- **Non-Indian regulatory regimes.** Underwrite targets RBI Digital
  Lending Guidelines and DPDPA 2023. Other jurisdictions (FCA, CFPB,
  etc.) require a fork.