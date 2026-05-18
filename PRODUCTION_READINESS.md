# Production Readiness

## Runtime hardening

- **Deterministic state:** `ProtocolState` + JSON round-trip guarantees reproducible snapshots.
- **Invariant checks:** `assert_invariants()` validates graph structure, non-negative balances, and credit-limit feasibility on demand.
- **Idempotency:** API mutations support `Idempotency-Key` header with SHA-256 payload hashing to prevent replays and detect payload conflicts.
- **Thread safety:** API service uses `RLock` around state access and mutation.
- **Audit log:** `AppendOnlyLedger` records every state-changing event with UTC timestamps and contiguous sequence numbers.
- **Schema versioning:** State serialization includes `schema_version`; loaders reject unknown versions.

## Observability

- `GET /health` — liveness
- `GET /ready` — invariant-checked readiness (503 if broken)
- `GET /metrics` — Prometheus plaintext metrics (`ulu_requests_total`, `ulu_request_errors_total`, `ulu_request_latency_seconds_total`, `ulu_idempotency_hits_total`, `ulu_idempotency_conflicts_total`)
- `GET /admin/graph` — sponsor-forest inspection
- `GET /admin/solvency` — per-user required delegation
- `GET /admin/utilization` — seed delegation utilization

## Error handling

- `ProtocolError` (400) — invalid inputs, unknown users, malformed state
- `InfeasibleOperationError` (400) — solvency or feasibility violations
- `InvariantViolationError` (400/503) — structural or accounting inconsistency
- `UnknownUserError` (400) — missing user reference

## Persistence

- `POST /state/save` and `POST /state/load` for JSON snapshots
- `POST /ledger/save` and `POST /ledger/load` for JSONL audit streams
- `POST /admin/reset` for runtime reset without restart

## Assumptions and limits

- One active loan per borrower at origination (`x_u = 0` precondition).
- Default probability `D_v` is exogenous; the optional risk model module supplies it but is not required for the core mechanism.
- Floating-point arithmetic uses an `epsilon` tolerance (`1e-12`) for invariant checks.
- No recovery, servicing costs, correlated shocks, dynamic reputation, or coalition logic in the baseline.
