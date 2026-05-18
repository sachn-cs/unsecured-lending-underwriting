# Gap Analysis

## What existed before this revision

- Core mechanism (`ulu/mechanism.py`) implementing delegation, revocation, default propagation, and pricing.
- Ledger (`ulu/audit/ledger.py`) with JSONL persistence.
- API (`ulu/api/app.py`) with FastAPI endpoints, idempotency, metrics, and health checks.
- Risk model (`ulu/risk_model.py`) as optional extra.
- Tests (`tests/`) covering conservation, revocation, default, premium logic, and persistence.
- Minimal `demo.py`.
- Missing docs: no `FIDELITY_REPORT.md`, `GAP_ANALYSIS.md`, or `PRODUCTION_READINESS.md`.

## Gaps found during audit

### 1. Default propagation: seed earned-credit double burn

**Issue:** `default()` loop burns earned credit at each sponsor, including the seed. After the loop, a redundant block attempted to burn the seed's earned credit again before touching base budget.

**Impact:** Benign in aggregate totals (second burn is zero when loss > 0, because the loop already exhausted earned credit), but violates the paper's algorithm verbatim.

**Fix:** Removed the redundant `absorb_seed` step in `default()`. After the loop, remaining loss is charged directly to `base_budget[seed]`.

### 2. Google Python Style Guide violations (camelCase)

**Issue:** Helper methods and functions used camelCase instead of snake_case.

**Affected files:**
- `ulu/mechanism.py`: `edgeKey`, `edgeTuple`, `recordEvent`
- `ulu/audit/ledger.py`: `eventsStore`, `utcNowIso`, `eventFromRow`
- `ulu/risk_model.py`: `buildModelSpecs`, `vectorToParams`, `clipVector`, `scoreModel`, `runPso`, `brierWithRegularization`, `greedyRegularizedWeights`, `buildMetaFeatures`, `checkFitted`
- `ulu/api/app.py`: `metricsMiddleware`, `safeCall`, `ledgerEventsPayload`, `graphPayload`, `canonicalRequestHash`, `idempotentMutation`, `quoteResponsePayload`
- `demo.py`: `quoteReport`

**Fix:** Renamed all to snake_case.

### 3. Missing theorem-level edge-case tests

**Issue:** Tests covered happy paths but missed edge cases for:
- Empty protocol state (no seeds yet)
- Non-seed with no children
- Borrower with no active loan
- Default where earned credit absorbs entire loss before reaching seed
- Revocation at exact boundary (`new_delegation == R_v`)
- Quote on borrower with zero credit limit

**Fix:** Added explicit tests for all of the above.

### 4. Missing documentation

**Issue:** README referenced `FIDELITY_REPORT.md`, `GAP_ANALYSIS.md`, and `PRODUCTION_READINESS.md` but none existed. No `docs/` directory.

**Fix:** Created all three docs plus `docs/` guides for setup, running, revocation, default handling, pricing, and theorem evaluation.

### 5. Demo script too minimal

**Issue:** `demo.py` only ran a hard-coded flow with no theorem evaluation or inspection.

**Fix:** Enhanced `demo.py` to print theorem checks and state summaries.

## What remains partial

- **Risk model (`ulu/risk_model.py`):** The risk model is a separate arXiv paper (2603.18927) and is treated as an optional extension. It is not part of the baseline mechanism fidelity.
- **API (`ulu/api/app.py`):** Operational wrapper; not part of the paper's mechanism specification, but included for usability.
