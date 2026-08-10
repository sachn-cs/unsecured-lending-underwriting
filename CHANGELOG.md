# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Note:** Historical entries (pre-v0.9) reference module filenames like
> `underwrite/__bus__.py`. As of v0.9 the core infrastructure modules use bare
> names (`underwrite/bus.py`, `underwrite/store.py`, etc.). The only remaining
> `__<name>__.py` files in the package are `__init__.py`, `__main__.py`, and
> the auto-generated `__version__.py`.

## [Unreleased]

### Added
- `LocalBus.is_stopped()` and `LocalBus.subscriber_count()` public accessors;
  runtime bus health probe now reports the real subscriber count and
  stopped-state instead of always returning `ok: True`.
- Runtime identity, `Event.canonical_sign_bytes()` (binds source),
  `AccessControl.set_replay_window()` and
  `AccessControl.is_trusted()`.
- `Identity.to_pem()` and `Identity.persist()`; new
  `Identity.create(secrets_manager=...)` flow persists Ed25519
  keys through the configured secrets backend so provenance
  survives restarts.
- `Runtime.publish_as(source, event_type, payload, correlation_id)`
  binds the publisher identity; `/v1/publish` now requires a
  `source` field and uses this path.
- `RazorpayClient.webhook_secret()` accessor; the service refuses
  webhooks when no secret is configured and verifies against the
  configured client secret (never a value from the payload).
- `Plugins.discover()` allowlist via `UNDERWRITE_PLUGINS` env var.
- `PII_FIELD_PATTERNS` token-based field matching in
  `__pii__.PIISanitizer`; new `Event.canonical_sign_bytes()`.
- `DeadLetterQueue.put` redacts PII before persistence; the
  in-flight event in memory is untouched.
- `MetricsExporter.__format_tags` escapes backslash, double-quote,
  and newline; tag values are run through the PII redactor.
- Damped Newton-Raphson KFS APR with correct analytic derivative.
- `Decimal` EMI/APR arithmetic in pricing.
- Bounded handler buckets in `IdempotencyGuard` (default 1000).
- Self-expiring `DistributedRateLimiter` via per-key
  `{"expires_at": ...}` marker.
- `RetryPolicy.non_retryable_exceptions` parameter defaulting to
  programmer-error types.
- `Configuration._validate_data_dir` rejects sensitive system paths.
- `OtlpSpanExporter(insecure, headers)` for TLS / auth.
- `Configuration.to_dict` redacts every secret-shaped field across
  every config section.
- 3.10/3.11/3.12/3.13 CI matrix; TruffleHog secret scan; coverage
  gate (`--cov-fail-under=80`).
- Per-saga try/except in `SagaOrchestrator.__load_sagas`.
- 50+ regression tests covering each of the above.

### Changed
- **Logging** — migrated from stdlib `logging` to loguru. All call sites
  now use `{}`-style formatting; JSON and text formatting live in
  `underwrite/__logger__.py`. The text formatter reports a fixed platform
  identity, and the JSON formatter emits a `trace_id` when one is bound
  via `logger.bind(trace_id=...)`.
- **Compliance service** — from basic PAN/Aadhaar regex to PAN category detection, Aadhaar Verhoeff checksum, weighted keyword AML risk scoring (low/flagged/frozen), CKYC event emission, video KYC lifecycle hooks, consent pre-check
- **Pricing service** — from generic rate computation to RBI-compliant: per-product rate caps (home 12%, gold 18%, personal 28%, micro 30%), all-in-cost APR, penal interest cap (24%), foreclosure charge computation, EMI amortization, DTI calculation, GST disclosure
- **Recovery service** — from in-memory-only (state lost on restart) to store-backed persistence via TypedStoreRepository with duplicate default detection
- **__config__.py** — added `kfs`, `npa`, `dpdpa`, `razorpay`, `credit_bureau`, `underwriting` config sections; refactored SERVICE_NAMES to include consent, dsr, credit_bureau, kfs
- **__service_registry__.py** — wiring updated for new compliance/pricing/recovery event names
- **docker-compose.yml** — from filesystem-only to Postgres 16 + Vault + OTLP collector
- **Base service** — refactored `StatefulService` store_repo/batched_repo factory methods
- **PostgresStore** — migration engine uses lock_timeout and statement_timeout for safety
- `UNDERWRITE_AUDIT_EXPORT_URL` env var added for audit log offloading
- PII redaction — Aadhaar-like 12-digit and PAN-like patterns redacted in logs and audit
- `LocalBus` lifecycle: a freshly constructed bus is now considered running.
  `start()` is idempotent and flushes the buffer only on the first call.
- **Hardening pass (v0.9)**: PII regex rewrite, all math corrections,
  per-saga error isolation, bounded IdempotencyGuard, deque-based
  bus hot paths, dead test fixtures removed, single-source-of-truth
  `SERVICE_NAMES`, full Python CI matrix.

### Fixed
- `UNDERWRITE_RECOVERY_BACKOFF` env var now correctly maps to `recovery.backoff_seconds`
- `communication` service test isolation — removed flaky shared state dependency
- `UNDERWRITE_SECRETS_AWS_REGION` accepts empty string for fallback to env default
- `__secrets__` backend fallback ordering — Vault/AWS not tried when `backend=env`
- Vault `KVv2` secret path handling — mounts at correct engine path
- Fixed broken `docs/ARCHITECTURE.md` link in README (should be `architecture.md`)
- **CLI `underwrite health` and `/v1/health` always reported `ok: True`** —
  the bus health probe looked for a non-existent `_EventBus__subscriptions`
  attribute and a non-existent `is_stopped()` method, so every bus was
  reported healthy. Replaced with `LocalBus.subscriber_count()` and
  `LocalBus.is_stopped()`.
- **`Runtime.publish` always failed signature verification** — events were
  emitted with `source="runtime"` and an empty signature, so every authz-
  enabled subscriber routed the event to the DLQ. Runtime now holds an
  `Identity` for the `runtime` service, signs outbound events (binding
  event id, timestamp, type, source and payload), and registers its
  public key in the authz trust set.
- **Ed25519 signatures did not bind `event.source` and had no replay
  window** — the signed payload was `event_id:timestamp:event_type:payload`
  and a captured event verified forever. The canonical signed bytes
  (`Event.canonical_sign_bytes()`) now bind the source and the
  `AccessControl` enforces a 5-minute clock window
  (`AccessControl.set_replay_window` to override; set to 0 to disable).
- **Identity keys were in-memory only** — every restart generated a new
  Ed25519 keypair so historical events could no longer be verified.
  `Identity.create` now accepts a `SecretsManager`, loads an existing
  PEM key when present, and persists newly generated keys. New
  `Identity.to_pem()` / `Identity.persist()` helpers expose the private
  key for storage. `Runtime` and `NanoService` now plumb the runtime
  `SecretsManager` so service identities survive restarts.
- **Indian holiday calendar silently stopped working past 2027** — the
  moveable-holiday table was hard-coded to 2025–2027, so any due-date
  in 2028 or later missed Republic Day, Diwali, Eid and the rest. The
  table now extends through 2030 and queries for unknown years fall
  back to fixed holidays plus Sunday/2nd-Saturday/4th-Saturday rules
  with a logged warning rather than returning all-business-days.
- **`/v1/publish` accepted arbitrary source identity** — any client with
  the bearer token could publish events attributed to any source. The
  endpoint now requires a `source` field, validates its shape, looks
  up or lazily creates an Ed25519 identity for that source via the
  runtime `SecretsManager`, and signs the event with that identity.
  When authz is enabled, the source must be already trusted or the
  request is rejected.
- **Razorpay webhook signature verified against a client-supplied secret**
  — the service read `webhook_secret` from the untrusted event payload
  and passed it straight into the HMAC check, so an attacker could
  submit their own secret in a forged webhook and bypass the signature.
  The service now pulls the secret from the configured Razorpay client
  (`RazorpayClient.webhook_secret()`) and rejects webhooks when the
  client has no secret configured. Tests updated to set the secret
  on the mock client.
- **Plugin discovery loaded arbitrary code from any installed package**
  — `Plugins.discover()` iterated every `underwrite.services` entry
  point with no allowlist, so a typosquatted dependency could gain
  full process privileges. Plugins now require an explicit
  `UNDERWRITE_PLUGINS` allowlist; entry points not in the allowlist
  are logged and ignored. Setting `UNDERWRITE_PLUGINS=*` re-enables
  the legacy behaviour with a logged warning.
- **PAN validator rejected valid PANs** — `require_pan` accepted only
  4th-character letters `ABCFGHJLPT` (10 letters). Income Tax also
  issues PANs with 4th character `E` and `K`; the validator now
  accepts the full ITD set `ABCEFGHJKLPT` and rejects every other
  letter. New regression tests cover both directions.
- **PII field matching over-redacted innocent field names** — the
  `is_sensitive_field` test stripped underscores and then ran a
  raw substring search, so `pan` matched `company` and `panel_id`,
  `auth` matched `author`, `pin` matched `pinterest`. Field matching
  is now token-based: the key is split on non-alphanumeric boundaries
  and each token is tested for equality against the canonical PII
  field names. Regression tests cover the over-matching cases
  (company, panel_id, panchayat, author, pinterest) and the
  legitimate matches (user_pin_code, aadhaar_token, mobile_number).
- **DLQ stored full event payloads with PII** — `DeadLetterQueue.put`
  appended the raw `Event` to the in-memory and persistent DLQ, so
  PAN, Aadhaar, mobile numbers and other PII patterns persisted in
  the DLQ for the configured retention period. The DLQ now redacts
  the event payload (PII field names and value patterns) before
  storage; the in-flight event in memory is untouched. New
  regression test `test_put_redacts_pii` covers the path.
- **Prometheus exposition was vulnerable to label-value injection and
  PII persistence** — tag values were interpolated unescaped, so a
  user-controlled tag containing `"` or `\n` could break out of the
  label string and inject arbitrary exposition content. Tag values
  are now escaped for backslash, double-quote, and newline. Tag
  values are also run through the PII redactor so a misconfigured
  caller cannot persist PAN/Aadhaar/mobile numbers into the
  Prometheus TSDB.
- **KFS APR Newton-Raphson derivative was mathematically wrong** —
  the derivative formula in `compute_apr` did not match `PV(r)` so
  the iteration diverged or converged to the wrong APR for any
  non-trivial loan. Replaced with the correct analytic derivative
  `dPV/dr = EMI * [ - (1 - 1/u)/r^2 + n/(r(1+r)u) ]` and added
  damped Newton steps so the iteration stays bounded for long
  tenures and high APRs.
- **Pricing EMI used float `math.exp` for `(1+r)^n`** — precision loss
  for long tenures or high monthly rates. EMI is now computed with
  `Decimal` arithmetic and rounded to the nearest paisa.
- **Pricing silently clamped over-cap interest rates to the RBI cap**
  — RBI requires rejection. Over-cap requests now raise
  `ProtocolError` and emit no event. The internal
  `validate_interest_rate` helper now delegates to
  `compute_rate_cap` so the two cap dictionaries no longer disagree
  (previously personal was 0.24 in one and 0.28 in the other).
- **Amortization and foreclosure accepted any positive input** —
  `calculate_emi` accepted a 500% APR or a 1000-year tenure, and
  `calculate_foreclosure` accepted a negative or > 100% penalty
  rate. Add explicit bounds (annual_rate <= 100, tenure <= 100
  years, 0 <= penalty_rate <= 100) with `ValueError`. Also guard
  `project_outstanding` against negative payment amounts which
  previously inflated accrued interest instead of being rejected.
- **NPA classification off-by-one** — `classify_overdue_days(90)`
  returned ``standard`` even though 90 days past due is the RBI
  NPA threshold (an asset becomes NPA on day 90+). Switch to
  strict-less-than boundaries: ``< 90 → standard``, ``< 180 →
  substandard``, ``< 360 → doubtful``, ``else loss``. Negative
  days now raise. Tests updated to match RBI norms.
- **Reporting NPA ratio computed against cumulative originations**
  — the formula was ``npa / total_originated_principal``, which
  does not match the RBI definition. Use the ratio of
  NPA outstanding over total outstanding (sum of all bucket
  principals) instead.
- **Underwriter silently passed on rule evaluation error** — the
  rule engine logged a warning and returned ``passed = True``
  on TypeError/ValueError/IndexError, so a malformed rule or
  invalid fact value silently turned into an approval. Rules now
  fail closed: an evaluation error sets ``passed = False`` with
  an error log. New tests assert that string-typed numeric
  values no longer yield an approval.
- **AML-frozen users passed underwriter** — the default rule
  required ``aml_status == "cleared"`` so a frozen user with
  stale cleared data still got the same outcome as a never-frozen
  user. Replace with ``aml_status != "frozen"`` so the most
  recent AML state actually gates the decision.
- **Quote and mechanism emitted `protocol_premium` without a
  consistent unit interpretation** — the value was
  `pr * principal * term` (total interest over the term in
  currency units) but the field name implied a one-time fee.
  Both `mechanism` and `quote` now also emit `total_interest` with
  the same value, and a docstring clarifies the units. Downstream
  consumers should migrate to `total_interest`; `protocol_premium`
  is kept for backwards compatibility.
- **Bus hot paths used O(n) `list.pop(0)`** — `DeadLetterQueue.put`,
  `LocalBus.publish`, and the bus buffer all used ``list.pop(0)``
  for FIFO eviction, which is O(n) per call. Convert to
  ``collections.deque`` so the eviction is O(1) and the bus
  no longer degrades under sustained failure load.
- **IdempotencyGuard leaked handler buckets** — the outer dict
  mapping ``handler_id → set`` was unbounded. A misbehaving caller
  (or simply many service ids) could grow the dict forever.
  Add ``max_handlers`` (default 1000); the oldest handler bucket
  is evicted past the cap. New regression test covers the eviction.
- **Collection on_repaid looked up the wrong key** — the store was
  keyed by ``borrower`` (in on_loan_originated) but on_repaid
  read ``user``, so every repayment was a silent no-op. Now reads
  ``borrower`` (with a ``user`` fallback for backwards
  compatibility).
- **Fee service dedup substring match broke the cap check** —
  `total_assessed` was a substring match `loan_id in fee_id`,
  so loan `1` matched every fee containing `1`. Replace with a
  field comparison `r["loan_id"] == loan_id`.
- **Communication service emitted SENT without dispatching** —
  every `communication.send` event emitted `communication.sent`
  even when no delivery adapter ran, so downstream consumers
  treated queued messages as delivered. Add `__dispatch_channel`
  hook (default returns `queued`) and only emit SENT when the
  adapter confirms delivery. The default base class records intent
  with `delivery_status=queued`.
- **Servicing `daily_rate` was always 0** — `LOAN_ORIGINATED`
  did not include `annual_rate` so servicing accrued no interest.
  Mechanism now reads `annual_rate` (defaulting to `protocol_rate`
  if absent) and includes it in the emitted event.
- **Credit bureau silently fell back to mock client without API
  key** — production with a missing `cibil_api_key` would answer
  with pre-seeded fake CIBIL data. The service now raises
  `RuntimeError` unless `allow_mock=True` is explicitly passed
  (intended for tests only).
- **Second-precision ID collisions across services** — fee, DSR,
  payment, and origination services generated IDs of the form
  ``{prefix}_{user}_{int(timestamp)}`` which collided for any two
  events in the same second for the same user. Replace the
  timestamp suffix with a 12-character hex UUID; collision-free
  even under burst load.
- **PostgresStore retried programmer errors 3× with backoff** —
  `RetryPolicy.execute` retried any `Exception` including
  TypeError/ValueError from a non-JSON-serializable value, wasting
  ~1.5s before crashing. Add a `non_retryable_exceptions` parameter
  defaulting to programmer-error types; callers must opt in by
  listing them in `retryable_exceptions` to retry them. PostgresStore
  now retries only on `OperationalError`, `InterfaceError`,
  `ConnectionResetError`, `TimeoutError`.
- **One corrupted saga dropped every in-flight saga on startup**
  — `SagaOrchestrator.__load_sagas` did a single try/except over
  the entire loop, so any deserialisation error wiped the
  in-memory saga state. Each saga is now loaded, parsed, and
  validated independently; the only thing that fails wholesale
  is the store-level `keys()` enumeration. Regression test
  covers the corrupt-record path.
- **DistributedRateLimiter permanently blocked after first event**
  on non-TTL stores — the limiter wrote `True` to the store
  with no expiration, so the next call saw a "key exists" and
  refused the event forever. Switch the stored value to
  `{"expires_at": window_end}`; the limiter consults the timestamp
  and recycles expired windows. Works on MemoryStore, FileStore,
  and any Postgres backend without requiring server-side TTL
  support.
- **Configuration save leaked payment provider / bureau / identity
  secrets to disk** — `Configuration.to_dict` only redacted
  `secrets.token`, `identity.private_key`, and
  `identity.encryption_passphrase`. Razorpay `key_secret`,
  `webhook_secret`, `api_token`, every credit-bureau API key,
  and CKYC API key were persisted in plaintext on `config.save()`.
  The redaction list now covers every secret-shaped field across
  every config section.
- **Env-var overrides silently disabled features on parse error**
  — `UNDERWRITE_AUTHZ_ENABLED=garbage` was treated as False with
  only a debug log. The parser now logs a warning and leaves the
  default in place, never silently disabling a feature.
- **`Configuration.data_dir` accepted any path** — a config with
  `data_dir=/etc` would have the FileStore read/write system
  paths. Add a Pydantic field validator that rejects sensitive
  system paths (/, /etc, /proc, /sys, /var, /usr).
- **`.env.example` documented env vars that were silently ignored**
  — `UNDERWRITE_SQS_QUEUE_URL`, `UNDERWRITE_SQS_REGION`,
  `UNDERWRITE_MODAL_QUEUE_NAME`, `UNDERWRITE_COOLING_OFF_DAYS`,
  and the RBI pricing caps were listed but never read by
  `Configuration.__apply_env_overrides`. Document the variables
  that are actually honoured, add the missing ones
  (`UNDERWRITE_BUS_MAX_BUFFER_SIZE`, `UNDERWRITE_OTLP_ENDPOINT`,
  `UNDERWRITE_REQUIRE_AUTH`, `UNDERWRITE_ALLOW_JOBLIB`,
  `UNDERWRITE_PLUGINS`, `VAULT_TOKEN`), and remove the dead ones
  with a comment explaining the no-env-override services.
- **CI matrix tested only Python 3.12** — README claims 3.10–3.13
  support but `ci.yml` ran on 3.12 only. Expand the matrix to
  3.10/3.11/3.12/3.13; add a coverage gate
  (`--cov-fail-under=80`); switch `ruff format --diff` to
  `ruff format --check` so a non-formatted file fails CI; add a
  TruffleHog secret-scan job so committed secrets are caught
  before they land.
- **OTLP span exporter had no TLS/auth options** — the exporter
  was hard-coded to plaintext `http://localhost:4317` with no
  way to add auth headers. Add `insecure` and `headers` parameters
  and reject `http://` endpoints when `insecure=False` so
  production deployments cannot accidentally ship span data in
  cleartext.
- **ModalBus poll loop spun at 100% CPU during burst traffic** —
  the loop called `queue.get(block=False)` in a tight inner loop
  and only slept *after* the queue drained, so under load the
  poll interval was never honoured. Move the sleep to the top of
  each iteration.
- **`SERVICE_NAMES` was duplicated in `__config__` and the
  service registry** — adding a new service meant editing two
  files; one had drifted out of sync. `SERVICE_NAMES` is now
  derived from the registry's `SERVICE_CLASSES` keys, which is
  the single source of truth.
- **AsyncBus dispatch loop woke every 1s when idle** — the loop
  used `asyncio.wait_for(queue.get(), timeout=1.0)` which forced
  a wasted wakeup on every idle tick. Switch to
  `asyncio.wait({getter, stop_event})` so shutdown is
  immediate. Use `inspect.isawaitable` instead of duck-typing
  `hasattr(result, '__await__')` for the awaitable detection.
- **SqsBus deleted the message after the inner `try`/`except`
  regardless of whether dispatch succeeded** — if a handler
  raised, the message was deleted from SQS, losing the event
  forever. Reorder so the message is only deleted on full
  success; failed dispatches stay in flight and are redelivered
  by SQS after the visibility timeout, with the
  `IdempotencyGuard` absorbing any duplicate.
- **`/metrics-prometheus` had no authentication** — the endpoint
  is intended for internal scrape jobs but was wide open. Add
  bearer-token authentication that mirrors `/v1/publish`:
  when `UNDERWRITE_API_TOKEN` is set (or `api_token` is passed
  to `PrometheusMiddleware`), the endpoint requires
  `Authorization: Bearer <token>`. When no token is configured
  the endpoint is open (documented as acceptable for a private
  scrape network). Regression tests cover 200/401/wrong-bearer
  /no-token paths.
- **JSON log formatter had the same over-match bug as the
  audit PII redactor** — the formatter's `s in k.lower()` check
  matched `pan` against `company`, `tax` against `taxonomy`,
  etc. Switch to token-based matching that splits the key on
  non-alphanumeric boundaries and tests each token for set
  membership. New regression tests cover both directions.
- **Dead infrastructure removed**: `Identity.attest`,
  `KeyRotationManager`, and `IdempotencyError` were unused in
  production but kept for backwards compatibility. Removed
  from `__identity__.py`, `__exceptions__.py`, and
  `tests/test_identity_extras.py` (deleted). `docs/SECURITY.md`
  documents the new operator-driven rotation pattern using
  `AccessControl.trust()` and the replay window. All affected
  docs (FAQ, DEPENDENCIES, ARCHITECTURE, TROUBLESHOOTING, API,
  ADR-003, DIRECTORY_STRUCTURE, CODE_STYLE) updated.
- **Configuration.__merge was a hand-rolled Pydantic replacement**
  — ~100 lines of bespoke per-section copy/validate/raise code
  that duplicated `model_validate` and `model_dump`. Replaced
  with a single `overlay_section` helper that uses
  `model_validate({**base_dump, **overrides})` for every
  section. The fee, governance, kfs, npa, dpdpa, razorpay,
  credit_bureau, and underwriting sections now share the
  same overlay path; adding a new section means adding one
  line to a mapping instead of duplicating five lines of
  bespoke logic.
- **Real KYC provider integrations landed** — the four
  KYC integrations that were stubbed at the protocol level
  (PAN / Aadhaar eKYC / CIBIL / CKYC) now have full wire-protocol
  clients in `services/kyc_providers/`:

  - `pan.py` — ITD PAN verify via KYC service providers
    (Karza/Signzy); HMAC-SHA256 signed POST /v2/pan/verify
  - `aadhaar.py` — UIDAI KUA eKYC; pluggable KUA SDK via
    `_send_kyc_request` override
  - `cibil.py` — TransUnion CIBIL consumer bureau pull;
    POST /v2/cibil/score
  - `ckyc.py` — CERSAI CKYC registry search;
    POST /v1/ckyc/search

  Common surface in `base.py`: `Verdict` enum and
  `ProviderResult` envelope. `Configuration.kyc_providers`
  is the new Pydantic config block; secret-shaped fields
  (client_id, client_secret, kua_id, kua_license_key,
  partner_id, partner_key, search_provider_id,
  search_provider_key) are read from the configured
  `SecretsManager` and added to `Configuration.to_dict()`'s
  redaction list so `config.save()` never persists them.
  Compliance and credit-bureau services consume the
  configured providers; without them, they fall back to
  format-only validation (the v0.9 behaviour). Runtime
  auto-injects the providers via the new
  `Runtime.__build_kyc_providers` helper. 21 new tests in
  `tests/test_kyc_providers.py`.
- **`SecretsManager.get` / `SecretsManager.set`** — added
  generic key/value accessors so the KYC provider factory
  can read client secrets by canonical key
  (`underwrite/pan/client_id`, `underwrite/aadhaar/kua_id`,
  etc.) without hard-coding the loader semantics.
- **Dead infrastructure removed in the cleanup pass**:
  `Identity.attest`, `KeyRotationManager`, and
  `IdempotencyError` were unused in production code. Removed
  from `__identity__.py`, `__exceptions__.py`, and
  `tests/test_identity_extras.py` (deleted). Operator-driven
  rotation is now documented in `docs/SECURITY.md` using
  `AccessControl.trust()` and the replay window. All affected
  docs updated.
- **`Configuration.__merge` was a hand-rolled Pydantic
  replacement** — ~100 lines of bespoke per-section copy /
  validate / raise code. Replaced with a single
  `overlay_section` helper that uses
  `model_validate({**base_dump, **overrides})` for every
  section. Adding a new section now means adding one line to
  a mapping instead of duplicating five lines of bespoke logic.
- **Production Docker image**: `Dockerfile` is now a proper
  multi-stage build with a non-root user, OCI labels, build
  args for version / commit / build date, a `HEALTHCHECK`
  that pings `/healthz`, and a stripped `.so` runtime. CI
  workflow `.github/workflows/docker.yml` builds and smoke-
  tests the image on every push and on every tag. Local
  helper `scripts/build-image.sh`. `docker-compose.yml` adds
  the KYC production-mode env vars. `docs/DOCKER.md`
  documents the build / run / deploy workflow.
- **New docs**: `docs/KYC_INTEGRATIONS.md` documents the four
  KYC provider wire protocols, common surface, configuration,
  and sandbox vs production; `docs/ROADMAP.md` updated to
  mark the v0.9 items complete.

### Added Tests
- 138-line compliance test suite: PAN format + category, Aadhaar Verhoeff checksum, AML frozen/flagged/cleared, CKYC/video KYC events, consent pre-check, status queries
- 202-line recovery test suite: start/offer/accept/reject, escalation, partial/full payment, completion, store persistence, duplicate dedup
- Multi-saga concurrency tests — parallel saga execution with per-saga locks
- Notification channel dispatch tests (SES/Twilio)
- PII redaction edge-case tests (Aadhaar/PAN patterns)
- Circuit breaker open/half-open/close state transitions

### Removed
- stdlib `logging` integration — the `CorrelationFilter` and
  `log_context` thread-local moved to `underwrite/__correlation__.py`
  (a shared, stdlib-only module) with a `contextvars.ContextVar`
  backing, breaking the import cycle between logging and the service
  layer.
- `underwrite/version.py` (manual) — replaced by setuptools-scm auto-generated `__version__.py`
- `docs/api-reference.md`, `docs/getting-started.md`, `docs/index.md` — consolidated into docs/
- `TODO.md` — replaced by `docs/ROADMAP.md` and GitHub Issues
- `.pre-commit-config.yaml` (pre-commit hooks removed from repo)
- Flaky `test_communication.py` tests — removed 12 dead/duplicate test cases
- Misleading "Production-hardened" and "828+ tests" claims in README
- Dead test fixtures `FailAfterCountStore` and `InjectingBus` from `tests/conftest.py` —
  neither was imported by any test file.

### Security
- PII redaction — Aadhaar (12-digit), PAN, Voter ID, passport, bank account patterns masked in logs

---

## [0.6.2] — 2026-06-16

### Added
- SQS distributed event bus backend — production-scale event distribution
- Modal distributed event bus backend — serverless event bus
- DPDPA 2023 compliance configuration (consent, DSR, breach notification)
- RBI NPA provisioning rates (standard 0.25%, substandard 15%, doubtful 25%, loss 100%)
- SMA classification thresholds (SMA-0: 30d, SMA-1: 60d, SMA-2: 90d)
- Credit bureau multi-bureau config (CIBIL, Experian, Equifax + CKYC)
- Razorpay payment gateway config (UPI Autopay, e-NACH)
- KFS cooling-off period config (3 days per RBI DLG)
- Underwriting rules engine config (credit score, DTI, LTV caps)
- AML blocklist path env var for risk scoring
- Per-product RBI pricing cap env vars (personal, micro, penal)
- SQS/Modal bus env vars for distributed deployment

### Fixed
- `UNDERWRITE_RECOVERY_BACKOFF` mapping to correct config field
- Communication test isolation (removed shared state)
- AWS Secrets Manager fallback when `backend=env`
- Vault KVv2 path resolution
- `UNDERWRITE_SECRETS_AWS_REGION` empty-string handling

---

## [0.6.1] — 2026-06-15

### Added
- Compliance service: PAN category detection, Aadhaar Verhoeff checksum, AML risk scoring (keyword-weighted with low/flagged/frozen states), CKYC event emission, video KYC lifecycle hooks, consent pre-check
- Pricing service: RBI rate caps (home 12%, gold 18%, personal 28%, micro 30%), all-in-cost APR, penal interest cap (24%), foreclosure charges, EMI amortization, DTI, GST disclosure
- Recovery service: store-backed persistence via TypedStoreRepository
- Event registry: `aml.flagged`, `kyc.video_initiated`, `kyc.video_verified`, `pricing.penal_interest`, `pricing.foreclosure`, recovery.offer/escalated/progress
- Test suites: compliance (138 lines, 34 tests), recovery (202 lines, 15 tests), multi-saga concurrency

### Changed
- docker-compose.yml: filesystem → PostgreSQL 16 + Vault + OTLP collector
- `.env.example`: comprehensive env vars for all backends, compliance, pricing thresholds
- StatefulService: refactored store_repo/batched_repo factory methods
- PostgresStore: lock_timeout and statement_timeout for migration safety
- PII redactor: Aadhaar/PAN pattern coverage extended

---

## [0.6.0] — 2026-06-14

### Added
- Service registry wiring for 9 new Indian-lending event types
- `consent` and `dsr` to `SERVICE_NAMES` (were missing, preventing service enablement)
- Audit export URL env var for external audit log shipping
- Template-based `.env.example` with all sections documented

### Changed
- Config sections added: `kfs`, `npa`, `dpdpa`, `razorpay`, `credit_bureau`, `underwriting`
- `__config__.py` refactored for Indian lending parameters
- `__bus__.py` — improved backpressure handling and future tracking

### Fixed
- `__service_registry__.py` missing wiring for consent, dsr services
- `__bus__.py` — dead future reference cleanup on service shutdown

---

## [0.5.4] — 2026-06-10

### Added
- Async bus recovery — graceful reconnection on Redis/pub-sub failures
- Multi-saga concurrency test — parallel saga execution safety

### Fixed
- Saga rollback ordering — compensation events emitted in reverse step order
- Missing `correlation_id` propagation in saga compensation events
- Circuit breaker half-open timeout not resetting after success

---

## [0.5.3] — 2026-06-09

### Added
- PII pattern redaction for Aadhaar (12-digit), PAN (5 letters + 4 digits + letter)
- Voter ID and passport pattern redaction in logs
- Audit export URL config for remote log shipping

### Changed
- PostgresStore — query timeout configuration (lock_timeout, statement_timeout)
- Migration engine — transaction-per-version with explicit commit/rollback

### Fixed
- Postgres connection pool leak on migration failure
- `CircuitBreaker` state not resetting after recovery timeout
- `MetricsCollector` timer edge case with zero-duration operations

---

## [0.5.2] — 2026-06-08

### Added
- Distributed rate limiter — window-slot key pattern replacing TOCTOU get/set
- Postgres lock timeout safety for concurrent migration execution
- Dead-letter queue persistence across restarts (FileStore/PostgresStore)

### Changed
- `NanoService.__dispatch` — error logging includes correlation_id
- `SagaOrchestrator` — per-saga RLock instead of global lock
- `OtlpSpanExporter` — lazy SDK initialization at construction time

### Fixed
- Double event processing on service restart — idempotency guard extended
- `UNDERWRITE_BUS_MAX_WORKERS=0` now correctly disables thread pool

---

## [0.5.1] — 2026-06-07

### Added
- Notification channel dispatch — SES email + Twilio SMS via ThreadPoolExecutor
- Health check endpoint now reports per-service event counts
- `bus` property on `NanoService` for downstream access

### Changed
- `ServicingService` — refinanced loan handling with idempotency
- `postgres` extra now pins psycopg2-binary instead of psycopg2
- CI pipeline: Python 3.13 added to test matrix, 3.10 retained

### Fixed
- `ServicingService.handle()` — `self.bus` access via property instead of mangled attribute
- `disbursement/service.py` — missing `logger` import
- Document service UUID collision — full 32-char hex UUID
- Mechanism zero-recovery — `__default` includes principal field in payload

---

## [0.5.0] — 2026-06-06

### Added
- Comprehensive 37-page documentation site under `docs/` — architecture, system design, domain model, API reference, deployment, operations, security, troubleshooting
- 4 Architecture Decision Records (ADR): nano-service architecture, event-driven communication, Ed25519 provenance, saga orchestration
- `setup.sh` — idempotent environment bootstrap (venv, deps, pre-commit, validation)
- `lint.sh`, `test.sh`, `format.sh`, `cleanup.sh` — standalone scripts
- CI security scanning: bandit static analysis + pip-audit dependency auditing
- Docker build + smoke test in CI pipeline
- Postgres testcontainer fixtures, HTTP TestClient fixture, failure-mock fixtures in conftest.py
- `UNDERWRITE_ALLOW_JOBLIB` env var to gate joblib deserialization (disabled by default)
- `RISK_MODEL_SHA256` verification for risk model file integrity

### Changed
- PostgresStore pool: hand-rolled list+lock → psycopg2.pool.ThreadedConnectionPool
- MechanismService: snapshot/rollback pattern with state_lock held during store write
- Sagas: global RLock → per-saga RLock for concurrent execution
- Each migration version wrapped in its own transaction
- Risk model: JSON by default; joblib requires explicit opt-in
- Fee payment check moved entirely inside state_lock

### Fixed
- Event signature forgery — removed `json.dumps(default=str)` from signing
- Silent data loss — StoreRepository.save() no longer swallows Exception
- Double disbursement — idempotency guard in disbursement service
- Concurrent mutation loss — state lock held across store write
- Container ran as root — added USER underwrite to Dockerfile
- Port mismatch — docker-compose.yml port changed to 8000:8080

### Security
- Ed25519 signature verification enforced on all events
- Risk model integrity — SHA-256 verification; joblib gated behind explicit opt-in

---

## [0.4.0] — 2026-06-03

### Added
- Service lifecycle — supervisor auto-restart with configurable backoff
- Dead-letter queue — event capture, inspection, and replay via CLI
- Window-slot rate limiter for bus subscribers
- `__supervisor__.py` — monitors and restarts failing services
- `UNDERWRITE_RECOVERY_AUTO_RESTART`, `MAX_RESTARTS`, `BACKOFF` env vars
- Dead-letter queue persistence with CLI replay (`underwrite dlq --replay`)

### Changed
- `AsyncLocalBus` — per-handler timeouts (30s), CancelledError handling
- `__config__.py` — env var overrides for recovery settings
- Configuration loading — strict validation of unknown keys raises ConfigurationError
- Test isolation — all integration tests use dedicated store/bus instances

### Fixed
- Dead-letter queue records persist across bus restarts
- MemoryStore eviction distinguishes new keys from key updates
- Service dispatch no longer silently drops handler exceptions
- Bus health endpoint validates bus isn't stopped (not just alive)

### Security
- `UNDERWRITE_AUTHZ_ENABLED` gating for Ed25519 signature verification
- Authorization policy file support via `UNDERWRITE_AUTHZ_POLICY_FILE`
- Crypto availability warning when `cryptography` library is missing

---

## [0.3.3] — 2026-05-31

### Added
- Configuration recovery settings — auto_restart, max_restarts, backoff_seconds
- Service supervisor — monitors registered services, restarts on failure

### Changed
- `AsyncLocalBus` — improved concurrency with per-handler futures tracking
- Configuration loading — unknown keys raise ConfigurationError

### Fixed
- DLQ records now correctly persist across bus restarts
- MemoryStore eviction correctly distinguishes new inserts from updates
- Service dispatch no longer silently drops slow-handler exceptions

---

## [0.3.2] — 2026-05-29

### Added
- Kubernetes liveness/readiness probes (/healthz, /readyz)
- bandit security linter configuration in pyproject.toml
- Docker health check instruction

### Changed
- Port mapping fix: docker-compose host 8000 → container 8080
- Container user: root → underwrite (UID 1001)
- PostgresStore uses psycopg2.pool.ThreadedConnectionPool

### Fixed
- Dockerfile — addgroup/adduser with USER underwrite
- docker-compose.yml — added restart: unless-stopped

---

## [0.3.1] — 2026-05-27

### Added
- `uv.lock` — deterministic dependency lockfile
- Notification service — base channel dispatch infrastructure
- Document service — template rendering and PDF generation stubs

### Changed
- Risk model loading — lazy sklearn imports; model loaded on first handle()
- `__runtime__.py` — readonly mode for health/metrics without service startup

### Fixed
- ServicingService.handle() accesses self.bus via public property
- Missing logger import in disbursement/service.py

---

## [0.3.0] — 2026-05-26

### Added
- Circuit breaker infrastructure — per-subscriber failure tracking
- Per-handler timeout (30s) — slow handlers routed to DLQ
- Event payload size validation (>1 MB raises ProtocolError)
- `UNDERWRITE_BUS_MAX_FUTURES` configurable pending futures limit

### Changed
- British → American English in all docstrings
- logger.debug(exc_info=True) → logger.warning in bus trim_futures
- Metrics export interval configurable via env var

### Fixed
- MemoryStore eviction: distinguishes new keys from updates
- AsyncBus dispatch loop: handles CancelledError for clean shutdown

---

## [0.2.0] — 2026-05-25

### Added
- `.env.example` — documented all UNDERWRITE_* environment variables
- `.pre-commit-config.yaml` — pre-commit hooks for linting/formatting
- Test suites: bus extras, fee, fraud, mechanism, saga, store
- TODO.md — project roadmap (since replaced by docs/ROADMAP.md)

### Changed
- `__bus__.py` — DLQ replay support; configurable rate limiter window
- `__config__.py` — Configuration.default() returns sensible defaults
- `__cli__.py` — underwrite init creates config with mechanism + audit enabled
- PII redaction — field name matching uses case-insensitive regex

### Fixed
- Identity key TTL enforcement with grace period
- Store DSN parsing for Postgres connection strings with special characters

### Security
- PII redactor masks passwords, tokens, SSNs, credit card numbers, API keys in logs
- `UNDERWRITE_AUTHZ_ENABLED` defaults to true

---

## [0.1.1] — 2026-05-22

### Added
- CONTRIBUTING.md, SECURITY.md
- conftest.py — shared test infrastructure
- Test suites: audit, configuration, concurrency faults, risk faults, runtime faults, secrets faults, supervisor faults

### Changed
- Access control — service identity binding with key rotation
- Event bus — subscriber registration validates handler signatures
- CLI — list, health, dlq, metrics with structured output
- Config — env var overrides for all subsystems

### Fixed
- pyproject.toml setuptools package discovery (non-recursive find)
- mypy type errors across codebase

---

## [0.1.0] — 2026-05-20

### Added
- Initial nano-service platform implementation
- Core infrastructure: event bus, state store, saga orchestrator, access control, circuit breaker, configuration, runtime, CLI, FastAPI HTTP server
- Event system: typed EventType enum, Ed25519 cryptographic signatures
- 28 nano-services: mechanism, risk (ML), fraud, KYC/AML, collateral, fee, origination/servicing, collections, recovery, notifications, document, governance, pricing, provisioning, disbursement
- Pluggable stores: MemoryStore, FileStore, PostgresStore
- Observability: Prometheus metrics, OpenTelemetry tracing, structured JSON logging with PII redaction
- Resilience: dead-letter queue, retry policies, circuit breakers, idempotency guards
- HTTP API: /v1/health, /v1/metrics, /v1/publish with bearer auth and rate limiting
- Docker: multi-stage Dockerfile, docker-compose.yml
- CI/CD: GitHub Actions pipeline (lint, type-check, test across Python 3.10–3.13)
- Testing: 828+ tests across 58 test files (property-based, load, mutation, chaos)

---

[Unreleased]: https://github.com/sachncs/underwrite/compare/v0.6.2...HEAD
[0.6.2]: https://github.com/sachncs/underwrite/releases/tag/v0.6.2
[0.6.1]: https://github.com/sachncs/underwrite/releases/tag/v0.6.1
[0.6.0]: https://github.com/sachncs/underwrite/releases/tag/v0.6.0
[0.5.4]: https://github.com/sachncs/underwrite/releases/tag/v0.5.4
[0.5.3]: https://github.com/sachncs/underwrite/releases/tag/v0.5.3
[0.5.2]: https://github.com/sachncs/underwrite/releases/tag/v0.5.2
[0.5.1]: https://github.com/sachncs/underwrite/releases/tag/v0.5.1
[0.5.0]: https://github.com/sachncs/underwrite/releases/tag/v0.5.0
[0.4.0]: https://github.com/sachncs/underwrite/releases/tag/v0.4.0
[0.3.3]: https://github.com/sachncs/underwrite/releases/tag/v0.3.3
[0.3.2]: https://github.com/sachncs/underwrite/releases/tag/v0.3.2
[0.3.1]: https://github.com/sachncs/underwrite/releases/tag/v0.3.1
[0.3.0]: https://github.com/sachncs/underwrite/releases/tag/v0.3.0
[0.2.0]: https://github.com/sachncs/underwrite/releases/tag/v0.2.0
[0.1.1]: https://github.com/sachncs/underwrite/releases/tag/v0.1.1
[0.1.0]: https://github.com/sachncs/underwrite/releases/tag/v0.1.0
