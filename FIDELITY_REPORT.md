# Fidelity Report

Source: arXiv:2605.03307v1 — Unsecured Lending via Delegated Underwriting.

## Legend

- **Exact** — implementation matches paper formula/algorithm verbatim.
- **Approximate** — faithful structure, but a symbol or parameter is inferred from context.
- **Not determined** — paper does not specify enough detail to implement.

---

## Section 3.1 — Budgets and Credit Limits

| Item | Status | Notes |
|------|--------|-------|
| `E_s = \hat{E}_s + G_s` | Exact | `budget()` returns `base_budget + earned`. |
| `E_v = a_{p(v)\to v} + G_v` | Exact | `budget()` for non-seeds. |
| `c_u = E_u - \sum_{(u\to v)} a_{u\to v}` | Exact | `credit_limit()`. |
| Earned-credit update `G_u \leftarrow G_u + \Delta G_u` | Exact | `repay()`. |
| Theorem 1 (Credit conservation) | Exact | `total_credit_limit()` implements the LHS; tests verify equality with `sum base_budget + sum earned`. |

## Definition 1 — Required Delegation

| Item | Status | Notes |
|------|--------|-------|
| `R_v = max{0, x_v + \sum_{(v\to w)} R_w - G_v}` | Exact | `required_delegation()` recursive formula matches. |

## Theorem 2 — Revocation Solvency

| Item | Status | Notes |
|------|--------|-------|
| `a'_{u\to v} \ge R_v` | Exact | `revoke()` enforces `new_delegation >= required_delegation(child)`. |
| Increasing delegation guard | Exact | `revoke()` also checks sponsor `credit_limit` when increasing. |

## Section 3.2 — Default Propagation

| Item | Status | Notes |
|------|--------|-------|
| Borrower earned-credit burn | Exact | `default()` absorbs borrower earned credit first. |
| Upward loop: delegation reduction + sponsor earned burn | Exact | Matches paper loop for non-seeds. |
| Seed base-budget charge | **Approximate** | Code contains a redundant second earned-credit burn for the seed after the loop. Because the loop already burns seed earned credit when `v = p(j)` is the seed, the post-loop `absorb_seed` step double-counts. In practice the second burn is always zero (earned already exhausted in loop), so totals are correct, but the logic is not verbatim. **Fixed in this revision.** |
| Final `x_u \leftarrow 0` | Exact | `principal[borrower] = 0.0`. |

## Theorem 3 — Default Propagation Well-Defined

| Item | Status | Notes |
|------|--------|-------|
| Delegation reduction feasibility | Exact | Loop invariant `\ell \le R_j` is preserved by construction; `default()` raises `InvariantViolationError` if delegation is insufficient. |
| Seed base-budget non-overdraft | Exact | Seed base budget checked after loop. |

## Theorem 4 — Sponsor-Path Credit Limit Conservation

| Item | Status | Notes |
|------|--------|-------|
| Upstream nodes retain credit limit | Exact | Tests verify `credit_limit(v)` unchanged for `v != borrower` after default. |
| Aggregate credit falls by `x_u` | Exact | Tests verify `total_credit_limit` drops by exact principal. |

## Section 3.3.1 — Protocol Premium

| Item | Status | Notes |
|------|--------|-------|
| `I^R = r^R L_v T` | Exact | `protocol_premium` in `LoanQuote`. |
| Theorem 5 break-even rate | Exact | `protocol_break_even_rate()` returns `D_v / ((1-D_v)T)`. |
| Theorem 6 repay-then-default bound | Exact | Test verifies `\Delta G_v \le I^R` makes strategy weakly unprofitable. |

## Section 3.3.2 — Delegation Premium

| Item | Status | Notes |
|------|--------|-------|
| Definition 2 utilization `U^D` | Exact | `seed_delegation_utilization()` matches formula. |
| Delegation rate `r^D = r^D_max (1 - \bar{U}^D)` | Exact | `delegation_rate` in `LoanQuote`. |
| Definition 3 local buffer `b_u` | Exact | `local_buffer()` matches. |
| Definition 4 downstream buffer `B_k` | Exact | `downstream_buffers()` matches. |
| Theorem 7 feasibility / locked delegation `m_k` | Exact | `locked_delegation()` matches. |
| Sponsor payout `r^D m_k T` | Exact | `delegation_payouts` in `LoanQuote`. |
| Budget-balanced `I^D` | Exact | Test verifies `delegation_premium == sum(payouts)`. |

## Structural Invariants

| Item | Status | Notes |
|------|--------|-------|
| Rooted forest | Exact | `validateStructure()` enforces single parent, acyclicity, seed reachability. |
| Non-seed has exactly one sponsor | Exact | `parent` map + validation. |
| No cycles | Exact | `validateAncestryPaths()` raises on cycle. |

## Scope Limits (Paper Section 4)

| Item | Status | Notes |
|------|--------|-------|
| Recovery modeling | Out of scope | Explicitly excluded from baseline. |
| Servicing costs | Out of scope | Explicitly excluded. |
| Correlated shocks | Out of scope | Explicitly excluded. |
| Dynamic reputation | Out of scope | Explicitly excluded. |
| Coalition behavior | Out of scope | Explicitly excluded. |
| Richer underwriting signals | Out of scope | `D_v` is exogenous; risk model is a separate optional module. |

## Deviations

1. **Seed earned-credit double burn in `default()`** — benign in totals but not verbatim. Removed in this revision.
2. **camelCase naming** — Original code used camelCase for helpers (`edgeKey`, `recordEvent`, etc.). Google Python Style Guide requires snake_case. Renamed in this revision.
3. **`ProtocolConfig.epsilon`** — Paper uses exact real numbers; code uses a small `epsilon` for floating-point invariant checks. This is a pragmatic implementation detail, not a semantic deviation.

## Unknowns

None. Every formula and algorithm in the paper is recoverable from the HTML source.
