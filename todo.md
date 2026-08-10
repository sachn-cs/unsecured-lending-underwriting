# Underwrite Refactoring — Atomic Implementation Plan

> **Status**: plan only — no code changes yet. Each item below is one atomic commit. Items may be batched into PRs but stay independent commits.

## Naming conventions driving every change

These four principles explain almost every item below:

1. **No `__<name>__.py` filenames.** Files at the top level use bare names (`pii.py`, `bus.py`). The `__<name>__.py` convention sorts infrastructure modules to the top of directory listings, but it's anti-Pythonic and the only remaining benefit is sorting.
2. **No filename duplication in class names.** A multi-word class name may not share any word with its filename. `SecretsManager` in `secrets.py` becomes `Manager`. `HealthRegistry` in `health.py` becomes `Checks`.
3. **Single word when possible.** `DeadLetterQueue` → `Queue` because the `dlq.py` module already says "dead letter". `SagaOrchestrator` → `Orchestrator` because `saga.py` says "saga".
4. **No semi-private naming.** No `_x` or `__x` attribute or method prefixes. No `_internal.py` siblings. Composition over inheritance.

---

## Phase 0 — Pre-flight

| # | Change | Why |
|---|---|---|
| 0.1 | Run `./test.sh` and `./lint.sh`; save outputs as `preflight.txt` | Baseline so each subsequent phase can be diffed against known-good state |

---

## Phase 1 — Drop dead PII wrappers

| # | Change | Why |
|---|---|---|
| 1.1 | `pii.py`: delete `is_pii_field`, `contains_pii_value`, `redact_payload`, `is_pii_value`, `redact_text`. Reduce `__all__` to `[PII_FIELD_PATTERNS, PII_VALUE_PATTERNS, PII_REDACTED, PIISanitizer]`. Update tests | The five module-level wrappers duplicate `PIISanitizer` static methods one-for-one. AGENTS.md says "no backward-compat aliases" — delete instead of deprecate. Tests that called the wrappers switch to `PIISanitizer.*` directly |

---

## Phase 2 — Promote `_redact_event` to public `redact`

| # | Change | Why |
|---|---|---|
| 2.1 | `pii.py`: add public `redact(message: Message) -> Message` (the body of the old `_redact_event`) | PII redaction belongs in `pii.py`, not `bus.py`. Module-level privacy (`_`) violates the no-semi-private rule |
| 2.2 | `bus.py`: replace `_redact_event(event)` at the DLQ call site with `from underwrite.pii import redact` | Single call site; bus no longer owns PII logic |

---

## Phase 3 — Add missing `Type` entries (was `EventType`)

| # | Change | Why |
|---|---|---|
| 3.1 | `message.py`: add 11 enum entries (`AML_FLAGGED`, `KYC_VIDEO_INITIATED`, `KYC_VIDEO_VERIFIED`, `PRICING_PENAL_INTEREST`, `PRICING_PENAL_INTEREST_COMPUTED`, `PRICING_FORECLOSURE`, `PRICING_FORECLOSURE_COMPUTED`, `RECOVERY_OFFER`, `RECOVERY_OFFER_RESPONSE`, `RECOVERY_ESCALATED`, `RECOVERY_PROGRESS`) | `handler.py`'s `WIRING` table currently has these as ad-hoc string literals. Single source of truth: every bus event type lives in the `Type` enum |
| 3.2 | `handler.py`: replace 11 ad-hoc strings in `WIRING` with `Type.X.value` | Same reason — single source of truth |
| 3.3 — 3.12 | One commit per producer file: replace literal `"aml.flagged"` etc. with `Type.AML_FLAGGED.value` | Producers were passing ad-hoc strings; now they use the enum |

---

## Phase 4 — Single-word class renames

Module name provides the noun; class name drops the redundant word.

| # | Change | Why |
|---|---|---|
| 4.1 | `bus.py`: `DeadLetterQueue` → `Queue` | `dlq.py` already says "dead letter" |
| 4.2 | `bus.py`: `DeadLetterRecord` → `Record` | same |
| 4.3 | `bus.py`: `PerSubscriberCircuitBreaker` → `Breaker` | `circuit.py` already says "circuit" |
| 4.4 | `bus.py`: `RateLimiter` → `Limiter` | `rate_limit.py` already says "rate" |
| 4.5 | `bus.py`: `IdempotencyGuard` → `Guard` | `idempotency.py` already says "idempotency" |
| 4.6 | `bus.py`: `SubscriptionRegistry` → `Registry` | `subscription.py` already says "subscription" |
| 4.7 | `bus.py`: `AsyncDispatcher` → `Dispatcher` | `Async` prefix redundant when in `subscription.py` alongside `Registry` |
| 4.8 | `services/base.py`: `EventEmitter` → `Emitter` | "Event" prefix redundant; this is the only emitter in the file |
| 4.9 | `metrics.py`: `MetricsCollector` → `Collector`; `exporter.py`: `MetricsExporter` → `Exporter` | Module names supply "metrics" |
| 4.10 | `saga.py`: `SagaOrchestrator` → `Orchestrator` | Module supplies "saga" |
| 4.11 | `secrets.py`: `SecretsBackend` → `Backend`; `SecretsManager` → `Manager` | Module supplies "secrets"; user explicitly chose `Manager` despite AGENTS.md anti-suffix (the role is genuinely orchestration of multiple backends) |
| 4.12 | `health.py`: `HealthRegistry` → `Checks`; `supervisor.py`: `ServiceSupervisor` → `Watcher`; `kyc/base.py`: `KycProvider` → `Provider`; `kyc/config.py`: `KycProviderConfig` → `Config`; `exporter.py`: `ConsoleSpanExporter` → `Console`, `OtlpSpanExporter` → `Otlp` | Each module supplies the noun; class names drop it. `Watcher` chosen over `Supervisor` because the latter would duplicate the filename |

---

## Phase 5 — File rename sweep

| # | Change | Why |
|---|---|---|
| 5.1 — 5.30 | Mechanical `git mv` for each `__<name>__.py` → `<name>py`. Update `__all__` and imports in each file. Verify with `rg '__[a-z]+__\.py' underwrite/` returning zero at the end | Drop the `__<name>__.py` convention. Bare names are the Python standard; the convention only existed for alphabetical sorting in `ls` output |
| 5.31 | `bus_sqs.py` → DELETE | SQS backend removed (Phase 18 below) |
| 5.32 | `bus_modal.py` → `modal.py` | Single-word module name; `ModalBus` is the only public class |
| 5.33 | `prometheus_export.py` → DELETE; merge into `exporter.py` | All exporters live in one place; module `prometheus_export.py` only had module-level functions |
| 5.34 | `calendar_india.py` → `calendar.py` | Calendar is generic enough; Indian specifics are in the JSON table |

---

## Phase 6 — Extract DLQ

| # | Change | Why |
|---|---|---|
| 6.1 | create `dlq.py`: move `Queue`, `Record`, helpers (`event_to_dict`, `event_from_dict`, `record_to_dict`, `record_from_dict`, `__load_store`, `__sync_store`, `__should_sync`, `put`, `records`, `count`, `clear`, `replay`) | SRP — `bus.py` had 10 unrelated classes; DLQ is a self-contained concern with persistence logic |
| 6.2 | `bus.py`: re-export `Queue`, `Record` from `dlq.py` | Backward compatibility for any importers that used `bus.Queue` |

---

## Phase 7 — Extract Circuit Breaker

| # | Change | Why |
|---|---|---|
| 7.1 | `circuit.py`: add `Breaker` (was `PerSubscriberCircuitBreaker`) | `circuit.py` already exists; absorb the bus-extracted breaker |
| 7.2 | `bus.py`: re-export `Breaker` | Same as Phase 6.2 |

---

## Phase 8 — Extract Rate Limiter

| # | Change | Why |
|---|---|---|
| 8.1 | create `rate_limit.py`: `Limiter`, `DistributedLimiter` | Token-bucket algorithm is independent of pub-sub |
| 8.2 | `bus.py`: re-export | Same as 6.2 |

---

## Phase 9 — Extract Idempotency

| # | Change | Why |
|---|---|---|
| 9.1 | create `idempotency.py`: `Guard` | Bounded LRU with per-handler buckets — independent of bus mechanics |
| 9.2 | `bus.py`: re-export | Same as 6.2 |

---

## Phase 10 — Extract Subscription

| # | Change | Why |
|---|---|---|
| 10.1 | create `subscription.py`: `Registry` (subscription tracking) and `Dispatcher` (thread-pool executor bookkeeping) | Both deal with subscriber and executor management, not pub-sub routing itself |
| 10.2 | `bus.py`: re-export | Same as 6.2 |

---

## Phase 11 — Extract LocalBus

| # | Change | Why |
|---|---|---|
| 11.1 | create `local.py`: `LocalBus`, `AsyncLocalBus` | In-process bus implementation belongs in its own file; `bus.py` becomes the pure ABC |
| 11.2 | `bus.py`: re-export; final state is ~80 lines containing only `EventBus` ABC | The user explicitly chose `local.py` over `local_bus.py` per the single-word naming rule |

---

## Phase 12 — Promote Runtime factories

`Runtime` (697 LoC) had 17 private fields and 11 private factory methods. Promotion to top-level functions makes each independently testable.

| # | Change | Why |
|---|---|---|
| 12.1 | Promote `__build_secrets` → top-level `build_secrets(config)` | Each factory becomes independently testable without instantiating the full `Runtime` |
| 12.2 | Promote `__build_supervisor` → top-level `build_supervisor(config)` | Same |
| 12.3 | Promote `__build_kyc_providers` → top-level `build_kyc_providers(config, secrets)` | Same |
| 12.4 | Promote `__build_tracer` → top-level `build_tracer(config)` | Same |
| 12.5 | Promote `__build_store` / `__build_read_store` → top-level `build_store(config, data_dir)` / `build_read_store(config, data_dir)` | Same |
| 12.6 | Promote `__start_metrics_export` → top-level `start_metrics_export(metrics_collector, config)` | Same |
| 12.7 | Promote `__register_subsystem_health` → top-level `register_subsystem_health(runtime)` | Same; takes `runtime` explicitly so it reads through public properties |
| 12.8 | Promote `__run_migrations` → top-level `run_migrations(store, config)`; slim `Runtime.__init__` to <50 lines | Composition — `Runtime` becomes the orchestrator that wires the factories |

---

## Phase 13 — `Dependencies` dataclass

Service `__init__` methods take 13+ kwargs and forward them to `super().__init__`. Wrap them in a dataclass.

| # | Change | Why |
|---|---|---|
| 13.1 | `services/base.py`: add `Dependencies` dataclass with 11 explicit fields. Add `Core.from_dependencies(service_id, deps)` classmethod | KISS — service `__init__` body becomes 1-2 lines; explicit parameter list (no `**kwargs`) per no-semi-private rule |
| 13.2 — 13.31 | One commit per service: replace forwarding boilerplate; keep each service's public `__init__` signature stable | Reduces 13 lines per service to ~3 lines; explicit parameter list enforces the no-`**kwargs` rule |

---

## Phase 14 — `Message.signed` classmethod

`Emitter.emit` reconstructs an entire frozen Event to add one field (the signature). Centralize.

| # | Change | Why |
|---|---|---|
| 14.1 | `message.py`: add `Message.signed(keypair, *, type, source, source_key, payload, correlation_id="", trace_id="", parent_span_id="") -> Message` classmethod. Add `Keypair.sign_bytes(bytes)` helper | Centralizes the 20-line "construct → compute signature → reconstruct" dance |
| 14.2 | `services/base.py`: `Emitter.emit` shrinks from ~30 lines to ~10 | Reuses `Message.signed` instead of doing the dance inline |
| 14.3 | `runtime.py`: runtime-level signing helpers use `Message.signed` | Same |

---

## Phase 15 — Holidays JSON

| # | Change | Why |
|---|---|---|
| 15.1 | Move holiday data (2025-2030) from `calendar.py` (343 LoC of table data) to `data/holidays.json` | Data and code shouldn't be interleaved; JSON is editable without touching Python |
| 15.2 | `calendar.py` shrinks to ~40 lines: load JSON lazily, expose `is_holiday(date)`, `HOLIDAYS_BY_YEAR` | Locality — file becomes a thin loader, not a 343-line data dump |

---

## Phase 17 — Consolidate exporters

| # | Change | Why |
|---|---|---|
| 17.1 | `exporter.py`: move `Exporter`, `Console`, `Otlp` here from old modules | All exporters in one place — DRY, locality |
| 17.2 | Merge `prometheus_export.py` into `exporter.py` as `Prometheus`; delete old file | Same |
| 17.3 | Update all importers (`runtime.py`, `tracer.py`, `metrics_exporter.py` if not yet deleted) | Imports consolidate on `exporter` |

---

## Phase 18 — Remove SQS bus

| # | Change | Why |
|---|---|---|
| 18.1 | Delete `SqsBus`; remove `sqs` from `BusConfig.backend` validator (`config.py`); remove `sqs_queue_url` / `sqs_region` fields from `BusConfig` | Dead code — SQS backend was never wired up in tests; no production deployment uses it |
| 18.2 | Remove SQS branch from `runtime.py:build_bus`; remove `boto3` import; remove `aws` extra references in `pyproject.toml` if any | Same |

---

## Phase 19 — KYC directory rename

| # | Change | Why |
|---|---|---|
| 19.1 | `services/kyc_providers/` → `services/kyc/` | Single-word directory name |
| 19.2 | Update all importers (`config.py`, `runtime.py`, `compliance/handler.py`, `credit_bureau/handler.py`, tests) | New path |

---

## Phase 20 — Storage consolidation

Composition over inheritance. Postgres replaced by SQLite. No `_` prefix. No `**kwargs`.

| # | Change | Why |
|---|---|---|
| 20.1 | `pyproject.toml`: remove `postgres = ["psycopg2-binary>=2.9"]` extra and `psycopg2` from mypy overrides | SQLite replaces Postgres — one less external dependency |
| 20.2 | `config.py`: `StoreConfig.backend` validator: `{"memory", "filesystem", "postgres"}` → `{"memory", "disk", "sqlite"}` | Backend types renamed |
| 20.3 | `config.py`: same for `read_backend` | Same |
| 20.4 | `store.py`: delete `MemoryStore`, `FileStore`, `PostgresStore` | Composition replaces inheritance — `class XxxStore(Store)` was wrong per user direction |
| 20.5 | `store.py`: add `StoreBackend` Protocol | Documents the contract all backends satisfy |
| 20.6 | `store.py`: add `InMemory` class. Explicit `__init__()`, public `data` and `lock` attributes (no `_` prefix) | Standalone class — no inheritance from `Store` |
| 20.7 | `store.py`: add `Disk` class. Explicit `__init__(data_dir: str)`, public `data_dir` and `lock` | Same; `Disk` over `File` per user instruction |
| 20.8 | `store.py`: add `Sqlite` class. Explicit `__init__(path: str)`, public `path` and `connection`. Uses stdlib `sqlite3`; parameterized queries | Replaces Postgres with built-in SQLite — no external dependency |
| 20.9 | `store.py`: add `Store` façade. Explicit `__init__(type, data_dir, path)`, public `implementation` attribute, explicit delegation for `get`/`set`/`delete`/`exists`/`keys`/`health`/`shutdown`. No `**kwargs` | Façade for `Store(type="memory")` syntax; backends are usable directly |
| 20.10 | `store.py`: update `__all__` to `[Store, StoreBackend, InMemory, Disk, Sqlite, CQRSStore, ReadStore]` | Public surface reflects new names |
| 20.11 | `runtime.py`: `build_store` / `build_read_store` call `Store(type=..., data_dir=..., path=...)` | New constructor signature |
| 20.12 | `serve.py`: update direct Store construction | Same |
| 20.13 | `tests/conftest.py`: remove Postgres testcontainer; add `sqlite_store` fixture with `tempfile.NamedTemporaryFile(suffix=".db")` | Postgres tests gone, SQLite tests in |
| 20.14 | `tests/test_store.py`: replace `MemoryStore`/`FileStore`/`PostgresStore` references with `InMemory`/`Disk`/`Sqlite`. Add SQLite-specific tests | Tests follow renames |
| 20.15 | `underwrite/__init__.py`: re-export `Store, InMemory, Disk, Sqlite` | Public surface update |

---

## Phase 21 — Data modeling on services

Each service gets `id` (BSON-style, auto), `name` (human-readable, provided), `type` (class kind), `ref` (store key prefix), `created_at`, `updated_at` (ISO 8601).

| # | Change | Why |
|---|---|---|
| 21.1 | `services/base.py`: `Core.__init__(name, ...)` — replaces `service_id`. `self.id = utils.generate_id()` (BSON, auto). `self.name = name` (provided). `self.type = self.__class__.__name__`. `self.ref = f"{name}:"`. `self.created_at = self.updated_at = utils.now_iso()`. Drop `self.__service_id` (replace with public `self.id` / `self.name`) | Consistent data model across all services; BSON `id` for tracking, human-readable `name` for HANDLER_MAP lookup |
| 21.2 | `services/base.py`: update `Emitter.emit` to use `self.name` as event source | Events carry the service name (not id) — consumers look up by name |
| 21.3 — 21.32 | One commit per service (×30): rename `service_id` parameter → `name`. Pass `name="<service>"` to `super().__init__()`. Override `self.ref` per service (e.g., audit: `f"{name}:ledger"`). Update tests to use `service.name` and `service.id` | Each service gets the new data model; tests reflect it |

---

## Phase 22 — Data modeling on Keypair

| # | Change | Why |
|---|---|---|
| 22.1 | `keypair.py` (was `identity.py`): rename `service_id` field → `name`. Add `id: str = field(default_factory=generate_id)` (BSON). Add `type: str = "keypair"`, `ref: str = ""`, `updated_at: str = ""`. Change `created_at: float` → `created_at: str` (ISO). Update `Keypair.create()` to populate all fields. Use `field(default_factory=...)` for `sign_lock` | Keypair follows the same data model as services |
| 22.2 | Update all callers (~10 files): `keypair.service_id` → `keypair.name` (or `.id` for tracking); `created_at` is now ISO string | Same |

---

## Phase 23 — Service handler class rename

| # | Change | Why |
|---|---|---|
| 23.1 — 23.30 | For each service: in `services/<name>/handler.py` rename `XxxHandler` → `Handler`. Update `services/<name>/__init__.py` re-export. Update tests. Use the user-stated usage pattern: `from underwrite.services import audit; audit.Handler(...)` | Single-word class name; module name supplies context. Same `Handler` name in every service — module namespace distinguishes them. Usage `audit.Handler` makes the package the noun |

---

## Phase 24 — Drop HANDLER_CLASSES

| # | Change | Why |
|---|---|---|
| 24.1 | `handler.py`: drop `HANDLER_CLASSES` dict. `HANDLER_MAP` keys to module paths. `Runtime.register` does `getattr(module, "Handler")` | After Phase 23, every value in `HANDLER_CLASSES` is `"Handler"` — the dict carries no information beyond what `HANDLER_MAP` already has |

---

## Phase 26 — Identity / Event / EventType rename (~80 items)

| # | Change | Why |
|---|---|---|
| 26.1 | `identity.py` → `keypair.py`; `Identity` → `Keypair`; `IdentityError` → `KeypairError` | "Identity" is overloaded; "Keypair" matches the semantic role (Ed25519 keypair) |
| 26.2 | `events.py` → `message.py`; `Event` → `Message`; `EventType` → `Type` | "Message" is the canonical term for an envelope; "Type" is simpler than "EventType" |
| 26.3 | `exceptions.py`: `IdentityError` → `KeypairError` | Tracks the rename |
| 26.4 | `underwrite/__init__.py`: re-export `Keypair`, `Message`, `Type` | Public surface update |
| 26.5 | `handler.py`: `WIRING` uses `Type.X.value` | Tracking the rename |
| 26.6 — 26.34 | One commit per service (×30): update imports + body | Each service depends on these types |
| 26.35 — 26.79 | One commit per test file (~45): update imports + assertions | Tests reference the renamed symbols |
| 26.80 | `value_objects.py`: rename `paise_to_rupees(paise)` → `to_rupees(paise)`, `rupees_to_paise(rupees)` → `to_paise(rupees)`. Update all callers (~5 places). Update `Money.from_rupees` if it uses these | Concise naming — module context (`value_objects.py`) supplies "paise" understanding; function names drop the redundant prefix |

---

## Phase 27 — `utils.py`

User-requested override of AGENTS.md "no utils.py" rule.

| # | Change | Why |
|---|---|---|
| 27.1 | create `utils.py` with `generate_id` (BSON-style 24-char hex from stdlib `struct`/`os`/`socket`), `now_iso` (current UTC ISO 8601), `chunked`, `first`, `clamp`, `safe_divide`, `merge` | Single home for generic utilities used across subsystems. Each function small, single-purpose, free (no class wrapping). Domain helpers (`redact`, `to_rupees`, `calculate_emi`, `is_holiday`) stay in their dedicated modules |

---

## Phase 16 — Final validation

| # | Action |
|---|---|
| 16.1 | Run `./test.sh` and `./lint.sh`. Verify `rg '__[a-z]+__\.py' underwrite/` returns zero. Verify `rg 'self\.__\w+\|self\._\w' underwrite/` shows only opportunistic migration items. Run a smoke test of the Runtime end-to-end |

---

## Order of execution

```
Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11
        → 12 → 13 → 14 → 15 → 17 → 18 → 19 → 20
        → 21 → 22 → 23 → 24 → 26 → 27
        → 16
```

---

## Totals

| Metric | Value |
|---|---|
| Phases | 22 |
| Atomic commits | ~290 |
| Estimated effort | ~22 hours |
| Public API breaking changes | yes, by design (no aliases) |

---

## Final public API

```python
# Storage
from underwrite.store import Store, InMemory, Disk, Sqlite
store = Store(type="sqlite", path="./data.db")

# Bus
from underwrite.bus import EventBus
from underwrite.local import LocalBus
from underwrite.modal import ModalBus

# Service infrastructure
from underwrite.runtime import Runtime, Configuration
from underwrite.handler import HANDLER_MAP, WIRING

# Keypair
from underwrite.keypair import Keypair
kp = Keypair.create(name="audit")

# Messages
from underwrite.message import Message, Type

# Services
from underwrite.services import audit, risk, compliance
audit_svc = audit.Handler(name="audit", bus=bus, store=store, ...)

# Generic utilities
from underwrite.utils import generate_id, now_iso, chunked, first, clamp, safe_divide, merge

# Domain
from underwrite.pii import redact, PIISanitizer
from underwrite.value_objects import Money, Rate, to_rupees, to_paise
from underwrite.calendar import is_holiday
from underwrite.amortization import calculate_emi
from underwrite.validate import PayloadValidator
from underwrite.constants import MONEY_QUANTUM, RATE_QUANTUM
```

---

## Execution notes

- Each item is one atomic commit. Items may be batched into PRs but stay independent commits.
- Run `./test.sh` and `./lint.sh` after each phase; revert and fix before proceeding.
- Coverage must stay ≥ 80 % (CI gate).
- No backward-compat aliases (per AGENTS.md).
- Existing `self.__x` migrations are opportunistic; new code uses public attributes only.
- Each service rename is one commit. Don't bundle multiple services in a single commit.