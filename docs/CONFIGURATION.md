# Configuration

The underwrite platform is configuration-driven. A single JSON file controls
which services are enabled, how they connect to infrastructure (bus, store,
identity), and service-specific parameters.

---

## 1. Configuration Loading

At startup, `Configuration.load()` searches for a configuration file
in the following order:

1.  **Explicit path** — if a path argument is provided and the file exists,
    it is loaded immediately.
2.  **`UNDERWRITE_ENV`** — if set to e.g. `production`, the loader tries
    `config.production.json`.
3.  **`Configuration.default()`** — if no file is found, a sensible default
    configuration is used.

After file loading, `__apply_env_overrides()` overlays any matching
`UNDERWRITE_*` environment variables on top (see
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md)). Values that
fail to parse (e.g. `UNDERWRITE_AUTHZ_ENABLED=garbage`) are logged
and the default is left in place — features are never silently
disabled by a bad env var.

The `data_dir` field is validated against a deny-list of sensitive
system paths (`/etc`, `/proc`, `/sys`, `/var`, `/usr`) to prevent
a misconfigured `Configuration.data_dir=/etc` from clobbering
system files.

### Secret Redaction on Save

`Configuration.to_dict()` redacts every secret-shaped field across
every config section before the dict is written to disk by
`Configuration.save()`. The redaction list covers
`key_secret`, `webhook_secret`, `api_token`, `token`,
`private_key`, `encryption_passphrase`, `cibil_api_key`,
`experian_api_key`, `equifax_api_key`, and `ckyc_api_key`. There
is no path through the public API that persists these values
in plaintext.

```python
config = Configuration.load("underwrite.json")
config.save("audit-only.json")  # secrets are redacted
```

---

## 2. Pydantic Schema

`Configuration` extends `ForbidExtra` (which sets
`model_config = {"extra": "forbid"}`), so unknown keys in a JSON file cause a
`ConfigurationError`.

### Top-level fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `bus` | `BusConfig` | `BusConfig()` | Event bus settings |
| `store` | `StoreConfig` | `StoreConfig()` | Persistence backend |
| `logging` | `LoggingConfig` | `LoggingConfig()` | Log level/format/output |
| `identity` | `IdentityConfig` | `IdentityConfig()` | Ed25519 key material |
| `authz` | `AuthzConfig` | `AuthzConfig()` | Access control |
| `metrics` | `MetricsConfig` | `MetricsConfig()` | Metrics collection |
| `migration` | `MigrationConfig` | `MigrationConfig()` | Schema migration |
| `tracing` | `TracingConfig` | `TracingConfig()` | Distributed tracing |
| `saga` | `SagaConfig` | `SagaConfig()` | Saga orchestration |
| `secrets` | `SecretsConfig` | `SecretsConfig()` | Secrets backend configuration |
| `recovery` | `RecoveryConfig` | `RecoveryConfig()` | Auto-recovery settings |
| `fee` | `FeeConfig` | `FeeConfig()` | Fee schedules |
| `governance` | `GovernanceConfig` | `GovernanceConfig()` | Protocol governance parameters |
| `audit` | `AuditConfig` | `AuditConfig()` | Audit ledger limits |
| `kfs` | `KfsConfig` | `KfsConfig()` | Key Fact Statement config (RBI DLG) |
| `npa` | `NpaConfig` | `NpaConfig()` | NPA classification and provisioning (RBI) |
| `dpdpa` | `DpdpaConfig` | `DpdpaConfig()` | DPDPA 2023 data protection (India) |
| `razorpay` | `RazorpayConfig` | `RazorpayConfig()` | Razorpay payment gateway (India) |
| `credit_bureau` | `CreditBureauConfig` | `CreditBureauConfig()` | CIBIL/Experian/Equifax + CKYC |
| `underwriting` | `UnderwritingConfig` | `UnderwritingConfig()` | Underwriting rules and thresholds |
| `data_dir` | `str` | `"./data"` | Filesystem store data directory |
| `services` | `dict[str, ServiceConfig]` | `{}` | Per-service enablement/priority |

### BusConfig

| Field | Type | Default | Valid values |
|-------|------|---------|--------------|
| `backend` | `str` | `"local"` | `local`, `sqs`, `modal` |
| `rate_limit` | `float` | `0.0` | >= 0 (0 = unlimited) |
| `max_workers` | `int` | `0` | >= 0 (0 = synchronous dispatch) |
| `max_futures` | `int` | `10000` | >= 1 |

### StoreConfig

| Field | Type | Default | Valid values |
|-------|------|---------|--------------|
| `backend` | `str` | `"sqlite"` | `sqlite`, `memory` |
| `path` | `str` | `"./store.db"` | SQLite path. Use `:memory:` for an in-process database. |
| `busy_timeout` | `float` | `30.0` | Seconds. >= 0. |

### LoggingConfig

| Field | Type | Default | Valid values |
|-------|------|---------|--------------|
| `level` | `str` | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `output` | `str` | `"stdout"` | Free-form (e.g. `stdout`, `stderr`, file path) |
| `log_format` | `str` | `"text"` | `text`, `json` |

### IdentityConfig

| Field | Type | Default |
|-------|------|---------|
| `private_key` | `str` | `""` |
| `public_key` | `str` | `""` |
| `encryption_passphrase` | `str` | `""` |
| `key_ttl` | `float` | `86400.0` |
| `key_grace` | `float` | `3600.0` |

### AuthzConfig

| Field | Type | Default |
|-------|------|---------|
| `enabled` | `bool` | `true` |
| `policy_file` | `str` | `""` |

### MetricsConfig

| Field | Type | Default |
|-------|------|---------|
| `enabled` | `bool` | `true` |
| `export_interval` | `int` | `60` |

### TracingConfig

| Field | Type | Default | Valid values |
|-------|------|---------|--------------|
| `enabled` | `bool` | `false` | |
| `exporter` | `str` | `"console"` | `console`, `otlp`, `noop` |

### SecretsConfig

| Field | Type | Default |
|-------|------|---------|
| `backend` | `str` | `"env"` |
| `url` | `str` | `""` |
| `token` | `str` | `""` |
| `region` | `str` | `""` |

### RecoveryConfig

| Field | Type | Default |
|-------|------|---------|
| `auto_restart` | `bool` | `true` |
| `max_restarts` | `int` | `3` |
| `backoff_seconds` | `float` | `1.0` |

### KfsConfig (RBI Key Fact Statement)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cooling_off_days` | `int` | `3` | Free-look period per RBI DLG |
| `disclosure_version` | `str` | `"1.0"` | KFS template version |

### NpaConfig (RBI Asset Classification)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `standard_provisioning_rate` | `float` | `0.0025` | 0.25% provisioning for standard assets |
| `substandard_provisioning_rate` | `float` | `0.15` | 15% for substandard assets |
| `doubtful_provisioning_rate_secured` | `float` | `0.25` | 25% for doubtful secured assets |
| `loss_provisioning_rate` | `float` | `1.0` | 100% for loss assets |
| `sma_0_days` | `int` | `30` | SMA-0 threshold (30 DPD) |
| `sma_1_days` | `int` | `60` | SMA-1 threshold (60 DPD) |
| `sma_2_days` | `int` | `90` | SMA-2 threshold (90 DPD) |
| `npa_days` | `int` | `90` | NPA classification at 90 DPD |
| `dlg_trigger_days` | `int` | `120` | DLG trigger at 120+ DPD |

### DpdpaConfig (DPDPA 2023)

#### ConsentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `required_purposes` | `list[str]` | `[kyc_verification, credit_bureau_reporting, loan_servicing, collection, communication_transactional]` | Purposes for which consent is required |
| `consent_validity_days` | `int` | `365` | Consent validity period |
| `withdrawal_cooldown_days` | `int` | `0` | Cooldown before re-consent after withdrawal |

#### DsrConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `response_time_days` | `int` | `30` | DSR fulfillment timeline (DPDPA mandate) |
| `grievance_response_days` | `int` | `15` | Grievance response timeline |
| `dpo_email` | `str` | `""` | Data Protection Officer email |
| `dpo_phone` | `str` | `""` | Data Protection Officer phone |

DpdpaConfig top-level fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `consent` | `ConsentConfig` | `ConsentConfig()` | Consent management |
| `dsr` | `DsrConfig` | `DsrConfig()` | Data Subject Rights |
| `data_retention_years` | `int` | `8` | Data retention per IT Act |
| `kyc_retention_years` | `int` | `5` | KYC retention per PMLA |
| `breach_notification_hours` | `int` | `72` | Breach notification window |
| `enable_breach_detection` | `bool` | `true` | Enable breach detection |
| `enable_auto_purge` | `bool` | `false` | Auto-purge expired data |

### RazorpayConfig (Payment Gateway)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `key_id` | `str` | `""` | Razorpay API key ID |
| `key_secret` | `str` | `""` | Razorpay API key secret |
| `webhook_secret` | `str` | `""` | Webhook signing secret |
| `api_base_url` | `str` | `https://api.razorpay.com/v1` | API base URL |
| `upi_autopay_enabled` | `bool` | `true` | Enable UPI Autopay |
| `enable_nach` | `bool` | `true` | Enable e-NACH mandates |

### CreditBureauConfig (CIBIL / Experian / Equifax / CKYC)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cibil_enabled` | `bool` | `true` | Enable CIBIL check |
| `cibil_api_key` | `str` | `""` | CIBIL API key |
| `cibil_api_base` | `str` | `https://api.cibil.com/v1` | CIBIL API base |
| `experian_enabled` | `bool` | `false` | Enable Experian check |
| `experian_api_key` | `str` | `""` | Experian API key |
| `equifax_enabled` | `bool` | `false` | Enable Equifax check |
| `equifax_api_key` | `str` | `""` | Equifax API key |
| `ckyc_enabled` | `bool` | `true` | Enable CKYC verification |
| `ckyc_api_key` | `str` | `""` | CKYC API key |
| `ckyc_api_base` | `str` | `https://api.ckycindia.in/v1` | CKYC API base |
| `timeout_seconds` | `int` | `30` | HTTP timeout |

### UnderwritingConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_default_probability` | `float` | `0.25` | Max default probability for approval |
| `min_credit_score` | `int` | `650` | Min CIBIL/credit score |
| `max_dti_ratio` | `float` | `0.5` | Max debt-to-income ratio |
| `max_ltv_ratio` | `float` | `0.8` | Max loan-to-value ratio |
| `max_principal` | `float` | `10_000_000` | Max loan amount |
| `min_principal` | `float` | `1_000` | Min loan amount |
| `max_tenor_months` | `int` | `360` | Max loan tenure |

### ServiceConfig

| Field | Type | Default |
|-------|------|---------|
| `enabled` | `bool` | `false` |
| `priority` | `int` | `0` |

---

## 3. Environment Variable Overrides

Every configuration field can be overridden at runtime via
`UNDERWRITE_<SECTION>_<FIELD>` environment variables. The
`__apply_env_overrides()` method (`config.py:402`) iterates a hardcoded
mapping, coerces the string value to the target type, and updates the config
object.

Boolean coersion accepts `1`, `true`, `yes` (case-insensitive) for `True`;
everything else is `False`.

See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for the complete
alphabetical listing.

---

## 4. Validation

- **Schema-level**: Pydantic `field_validator` decorators enforce constrained
  values (e.g. `bus.backend` must be one of `local`, `sqs`, `modal`;
  `rate_limit` must be >= 0; `logging.level` must match a known log level).
- **File-level**: `Configuration.__merge()` (`config.py:288`) validates
  every section against its Pydantic model via `model_copy` + re-instantiation.
  Unknown top-level keys and unknown per-section fields raise
  `ConfigurationError` with a descriptive message.
- **Path traversal**: The loader rejects file paths containing `..`.

---

## 5. Serialization

```python
config.to_dict()  # → dict (strips secrets.token and identity.private_key)
config.save("path")  # → JSON file (creates parent directories)
```

`to_dict()` excludes `None` values and redacts sensitive fields (`token`,
`private_key`) so serialised output is safe to log or store.

---

## 6. Default Configuration

`Configuration.default()` (`config.py:222`) provides:

```python
Configuration(
    store=StoreConfig(backend="sqlite", path="./store.db"),
    services={name: ServiceConfig(enabled=False) for name in SERVICE_NAMES},
)
```

All other sections use their Pydantic model defaults (rate_limit=0, max_workers=0,
logging level=INFO, metrics enabled, etc.).

### Example configuration file (`underwrite.json`)

```json
{
    "bus": {
        "rate_limit": 100.0,
        "max_workers": 4,
        "max_futures": 10000,
        "max_buffer_size": 10000
    },
    "store": {
        "backend": "sqlite",
        "path": "./store.db"
    },
    "services": {
        "mechanism": {"enabled": true},
        "audit": {"enabled": true},
        "risk": {"enabled": true}
    }
}
```

> **Note**: `max_buffer_size` is accepted by `LocalBus.__init__()` but is not
> a field in `BusConfig`. Set it directly in JSON — it will be passed through
> at bus construction time.

---

## Available Services

The platform defines 28 nano services (`underwrite/config.py:461`):

`audit`, `collateral`, `collection`, `communication`, `consent`, `credit_bureau`,
`decision`, `disbursement`, `document`, `dsr`, `fee`, `fraud`, `governance`,
`graph`, `identity`, `kfs`, `mechanism`, `npa`, `notification`, `origination`,
`payment`, `pricing`, `quote`, `recovery`, `reporting`, `risk`, `servicing`,
`settlement`, `statement`, `underwriter`, `workflow`
