# ULU Admin Ops Runbook

## Purpose
Operational procedures for running the ULU API safely in production-like
environments.

## Startup
1. Start service:
```bash
uvicorn ulu.api:app --host 0.0.0.0 --port 8000
```
2. Verify liveness:
```bash
curl -f http://localhost:8000/health
```
3. Verify readiness:
```bash
curl -f http://localhost:8000/ready
```

## Core health and observability
- `GET /health`: process liveness.
- `GET /ready`: invariant-checked readiness.
- `GET /metrics`: Prometheus plaintext counters:
  - `ulu_requests_total`
  - `ulu_request_errors_total`
  - `ulu_idempotency_hits_total`
  - `ulu_idempotency_conflicts_total`
  - `ulu_request_latency_seconds_total`

## Idempotent mutation usage
Supported mutation endpoints accept optional `Idempotency-Key` header:
- `POST /seed`
- `POST /user`
- `POST /repay`
- `POST /revoke`
- `POST /originate`
- `POST /default`

Behavior:
- Same key + same payload: cached response replayed.
- Same key + different payload: `409 Conflict`.

Example:
```bash
curl -X POST http://localhost:8000/seed \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: seed-001" \
  -d '{"user":"s","base_budget":100.0}'
```

## Admin inspection endpoints
- `GET /admin/graph`: sponsor forest, parent map, and edge amounts.
- `GET /admin/utilization`: current seed-level utilization.
- `GET /admin/solvency`: invariant status and required delegation per non-seed.

## State and ledger operations
- Persist state: `POST /state/save` with file path.
- Load state: `POST /state/load` with file path.
- Persist ledger: `POST /ledger/save` with file path.
- Load ledger: `POST /ledger/load` with file path.

## Emergency reset
- `POST /admin/reset`

Effects:
- Reinitializes protocol state and ledger.
- Clears in-memory idempotency cache.
- Resets in-memory metrics counters.

Use only during incident response or test environment re-seeding.

## Incident playbook
1. `GET /ready`; if failing, capture error message.
2. Snapshot files:
   - `POST /state/save`
   - `POST /ledger/save`
3. Inspect:
   - `GET /admin/graph`
   - `GET /admin/solvency`
4. If unrecoverable, perform `POST /admin/reset` and reseed.

## Deployment verification
After deployment:
1. `GET /health` must return `200`.
2. `GET /ready` must return `200`.
3. `GET /metrics` must return counters.
4. Perform one idempotent mutation replay and verify stable response.
