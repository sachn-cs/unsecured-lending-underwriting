# Services

underwrite ships **34 wired nano-services** plus **4 KYC provider clients**
(in `underwrite/services/providers.py`). Every wired service extends `Core` (stateless)
or `StatefulService` (in-memory state), is registered in `underwrite/handler.py`
(`HANDLER_MAP`, `HANDLER_CLASSES`, `WIRING`), and has a dedicated test file
under `tests/test_<name>.py`.

## Tier A — fully self-contained (27 services)

No external network calls at runtime. Pure logic + signed event emission.
Safe to deploy without external credentials.

| Service | Lines | Purpose |
|---|---:|---|
| `audit` | 285 | Append-only PII-redacted event ledger |
| `mechanism` | 312 | Delegation state machine (seeds / users / loans) |
| `pricing` | 453 | RBI rate caps, EMI, all-in-cost APR, foreclosure |
| `kfs` | 246 | Key Fact Statement generation |
| `npa` | 309 | SMA / NPA / DLG asset classification |
| `recovery` | 364 | Multi-stage post-default recovery orchestration |
| `fraud` | 232 | Wash-trading + velocity detection |
| `underwriter` | 466 | Rule-based underwriting approval / rejection |
| `decision` | 179 | Signal aggregation + decision rules |
| `origination` | 142 | Loan application creation + submission |
| `servicing` | 295 | Loan servicing lifecycle |
| `statement` | 165 | Statement generation |
| `disbursement` | 125 | Disbursement recording |
| `payment` | 299 | Payment scheduling + overdue detection |
| `collection` | 219 | Collection state tracking |
| `collateral` | 173 | Collateral marking / valuation / liquidation |
| `document` | 125 | Document generation |
| `governance` | 193 | Parameter proposals + voting + execution |
| `graph` | 166 | Read-only graph queries (path / credit-limit / users) |
| `identity` | 77 | Identity registration |
| `quote` | 59 | Loan quote generation |
| `workflow` | 207 | Workflow orchestration (start / advance / complete) |
| `prepayment` | 111 | Prepayment processing |
| `fee` | 281 | Fee assessment (late / origination / prepayment / service) |
| `settlement` | 124 | Settlement completion |
| `reporting` | 209 | Report generation |
| `risk` | 143 | ML risk scoring (heuristic by default, sklearn optional) |

## Tier B — production-grade with optional live integrations (7 services)

Default is sandbox / mock; live mode engages via configured credentials +
`*_PRODUCTION=true` env vars. Each has explicit `is_configured()` /
`allow_mock` toggles.

| Service | Default | Live mode |
|---|---|---|
| `compliance` | PAN regex / Aadhaar Verhoeff / AML keywords | KYC provider clients in `services/providers.py` (PAN, Aadhaar, CIBIL, CKYC) |
| `credit_bureau` | `MockCreditBureauClient` | `HttpCreditBureauClient` (httpx) against CIBIL / Experian / Equifax / CKYC endpoints |
| `consent` | In-process consent lifecycle | Persisted via `Store` (Vault / Postgres for production keys) |
| `dsr` | In-process DSR fulfillment | Network delivery to data principal via configured channel |
| `razorpay` | `MockRazorpayClient` | `HttpRazorpayClient` (httpx) with HMAC webhook verification |
| `notification` | In-process dispatch | SES / SendGrid / Twilio / SNS via configured channel |
| `communication` | In-process dispatch | SMTP / Twilio / push via configured channel |

## Tier C — KYC provider libraries (4 clients)

Used by `compliance` and `credit_bureau`. Real wire-protocol clients, sandbox
by default, production URLs switchable via env vars
(`UNDERWRITE_PAN_PRODUCTION`, `UNDERWRITE_AADHAAR_PRODUCTION`,
`UNDERWRITE_CIBIL_PRODUCTION`, `UNDERWRITE_CKYC_PRODUCTION`).

| Provider | Wire endpoint | Auth |
|---|---|---|
| `pan` (Karza / Signzy) | `POST /v2/pan/verify` | HMAC over request body |
| `aadhaar` (UIDAI KUA) | `POST /api/kyc/v1/otp` + `/fetch` | KUA license key + signed XML |
| `cibil` (TransUnion CIBIL partner) | `POST /v2/cibil/score` | Partner ID + partner key |
| `ckyc` (CERSAI search) | `POST /ckyc-search/search` | Provider ID + provider key |

## Wiring

Every wired service subscribes to event types via the `WIRING` dict in
`underwrite/handler.py`. Wiring is declarative: `Runtime.wire()` iterates
the map and subscribes each listed service to its events at startup.
