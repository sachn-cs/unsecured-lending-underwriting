# Environment Variables

All `UNDERWRITE_*` environment variables override the corresponding JSON
configuration field at runtime. Additional variables control risk model
loading, notification channels, and secrets backend access.

---

## Configuration Overrides

Parsed by `Configuration.__apply_env_overrides()` in
`underwrite/config.py:402`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_BUS_BACKEND` | No | `local` | Event bus backend (`local`, `sqs`, `modal`) |
| `UNDERWRITE_BUS_RATE_LIMIT` | No | `0` | Max events/second per subscriber (`0` = unlimited) |
| `UNDERWRITE_BUS_MAX_WORKERS` | No | `0` | Thread pool size (`0` = synchronous dispatch) |
| `UNDERWRITE_BUS_MAX_FUTURES` | No | `10000` | Max pending futures before backpressure |
| `UNDERWRITE_SQS_QUEUE_URL` | No | `""` | AWS SQS queue URL (required when `BUS_BACKEND=sqs`) |
| `UNDERWRITE_SQS_REGION` | No | `""` | AWS region for SQS |
| `UNDERWRITE_MODAL_QUEUE_NAME` | No | `""` | Modal queue name (required when `BUS_BACKEND=modal`) |
| `UNDERWRITE_STORE_BACKEND` | No | `memory` | Store backend (`memory`, `filesystem`, `postgres`) |
| `UNDERWRITE_STORE_DSN` | No | `""` | Store connection string |
| `UNDERWRITE_STORE_POOL_SIZE` | No | `5` | Database connection pool size |
| `UNDERWRITE_STORE_READ_BACKEND` | No | `""` | Read-replica store backend (empty = use `STORE_BACKEND`) |
| `UNDERWRITE_STORE_READ_DSN` | No | `""` | Read-replica DSN (empty = use `STORE_DSN`) |
| `UNDERWRITE_LOG_LEVEL` | No | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `UNDERWRITE_LOG_OUTPUT` | No | `stdout` | Log output target |
| `UNDERWRITE_LOG_FORMAT` | No | `text` | Log format (`text`, `json`) |
| `UNDERWRITE_DATA_DIR` | No | `./data` | Filesystem store data directory |
| `UNDERWRITE_AUTHZ_ENABLED` | No | `true` | Enable access control |
| `UNDERWRITE_AUTHZ_POLICY_FILE` | No | `""` | Path to Rego/OPA policy file |
| `UNDERWRITE_METRICS_ENABLED` | No | `true` | Enable metrics collection |
| `UNDERWRITE_METRICS_EXPORT_INTERVAL` | No | `60` | Metrics export interval in seconds |
| `UNDERWRITE_TRACING_ENABLED` | No | `false` | Enable distributed tracing |
| `UNDERWRITE_TRACING_EXPORTER` | No | `console` | Tracer exporter (`console`, `otlp`, `noop`) |
| `UNDERWRITE_SAGA_ENABLED` | No | `true` | Enable saga orchestration |
| `UNDERWRITE_IDENTITY_KEY_TTL` | No | `86400` | Key rotation interval in seconds |
| `UNDERWRITE_IDENTITY_KEY_GRACE` | No | `3600` | Key overlap grace period in seconds |
| `UNDERWRITE_SECRETS_BACKEND` | No | `env` | Secrets backend (`env`, `vault`, `aws`) |
| `UNDERWRITE_SECRETS_VAULT_URL` | No | `""` | HashiCorp Vault server URL |
| `UNDERWRITE_SECRETS_VAULT_TOKEN` | No | `""` | Vault authentication token |
| `UNDERWRITE_SECRETS_AWS_REGION` | No | `""` | AWS region for Secrets Manager |
| `UNDERWRITE_RECOVERY_AUTO_RESTART` | No | `true` | Auto-restart crashed services |
| `UNDERWRITE_RECOVERY_MAX_RESTARTS` | No | `3` | Maximum restart attempts per service |
| `UNDERWRITE_RECOVERY_BACKOFF` | No | `1.0` | Initial backoff in seconds (exponential) |
| `UNDERWRITE_AUDIT_MAX_LEDGER` | No | `100000` | Max audit ledger entries before rotation |
| `UNDERWRITE_AUDIT_EXPORT_URL` | No | `""` | Audit log export endpoint |

---

## Environment Selector

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_ENV` | No | `""` | When set, loads `config.{value}.json` if no explicit config path is given |

---

## HTTP Server

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_API_TOKEN` | No | `""` | Bearer token required for all HTTP API requests (see `--require-auth`) |

---

## Risk Model

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RISK_MODEL_PATH` | No | `""` | Path to serialized risk model file |
| `RISK_MODEL_SHA256` | No | `""` | Expected SHA-256 hash of the model file (integrity check) |
| `UNDERWRITE_ALLOW_JOBLIB` | No | `""` | Set to `true` to enable `joblib` deserialization for pickle-based models |

---

## Secrets Backend

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VAULT_TOKEN` | No | `""` | Vault token (alternative to `UNDERWRITE_SECRETS_VAULT_TOKEN`) |
| `UNDERWRITE_SECRET_<NAME>` | No | — | Read secrets from environment; key is uppercased with `/` and `-` replaced by `_` |

---

## RBI Pricing Caps (India)

The pricing service has static rate-cap defaults that are read by
`compute_rate_cap` and `validate_interest_rate`. The four
product-specific caps are:

| Loan type | Default cap | RBI norm |
|-----------|--------------|----------|
| Home | 0.12 (12% p.a.) | 12% |
| Gold | 0.18 (18% p.a.) | 18% |
| Personal | 0.28 (28% p.a.) | 28% |
| Micro | 0.30 (30% p.a.) | 30% |
| Default (other) | 0.30 | 30% |

These are constructed as kwargs at `PricingService` construction time
and not overridden by environment variables. Construct a
`PricingService` with custom caps:

```python
from underwrite.services.pricing.service import PricingService

service = PricingService(
    service_id="pricing",
    rate_cap=0.24,
    penal_interest_cap=0.24,
)
```

`UNDERWRITE_COOLING_OFF_DAYS` is similarly not honoured at the
`Configuration` layer — pass `cooling_off_days=...` to
`KfsService` directly.

Over-cap requests are **rejected** with `ProtocolError`, not
silently clamped to the cap. This is the RBI-required behaviour:
the rate must be refused at origination, not laundered through
post-hoc clamping.

---

## AML / KYC (India)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AML_BLOCKLIST_PATH` | No | `""` | Path to JSON blocklist for AML screening (PEPs, sanctions, etc.) |
| `AML_THRESHOLD_LOW` | No | `10` | Score threshold for low-risk AML clearance |
| `AML_THRESHOLD_FROZEN` | No | `7` | Score threshold above which borrower is frozen |

---

## Credit Bureau / CKYC (India)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_CREDIT_BUREAU_CIBIL_ENABLED` | No | `true` | Enable CIBIL credit report check |
| `UNDERWRITE_CREDIT_BUREAU_CIBIL_API_KEY` | No | `""` | CIBIL API key |
| `UNDERWRITE_CREDIT_BUREAU_CIBIL_API_BASE` | No | `https://api.cibil.com/v1` | CIBIL API base URL |
| `UNDERWRITE_CREDIT_BUREAU_EXPERIAN_ENABLED` | No | `false` | Enable Experian credit report check |
| `UNDERWRITE_CREDIT_BUREAU_EQUIFAX_ENABLED` | No | `false` | Enable Equifax credit report check |
| `UNDERWRITE_CREDIT_BUREAU_CKYC_ENABLED` | No | `true` | Enable CKYC identity verification |
| `UNDERWRITE_CREDIT_BUREAU_CKYC_API_KEY` | No | `""` | CKYC registry API key |
| `UNDERWRITE_CREDIT_BUREAU_CKYC_API_BASE` | No | `https://api.ckycindia.in/v1` | CKYC API base URL |

---

## Razorpay Payment Gateway (India)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_RAZORPAY_KEY_ID` | No | `""` | Razorpay API key ID |
| `UNDERWRITE_RAZORPAY_KEY_SECRET` | No | `""` | Razorpay API key secret |
| `UNDERWRITE_RAZORPAY_WEBHOOK_SECRET` | No | `""` | Razorpay webhook signing secret |
| `UNDERWRITE_RAZORPAY_API_BASE_URL` | No | `https://api.razorpay.com/v1` | Razorpay API base URL |

---

## DPDPA 2023 Compliance (India)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_DPDPA_DATA_RETENTION_YEARS` | No | `8` | Borrower data retention period per IT Act/DPDPA |
| `UNDERWRITE_DPDPA_KYC_RETENTION_YEARS` | No | `5` | KYC data retention period per PMLA rules |
| `UNDERWRITE_DPDPA_BREACH_NOTIFICATION_HOURS` | No | `72` | Breach notification window to Data Protection Board |
| `UNDERWRITE_DPDPA_CONSENT_VALIDITY_DAYS` | No | `365` | Consent validity period for data processing |
| `UNDERWRITE_DPDPA_DSR_RESPONSE_DAYS` | No | `30` | Data Subject Request fulfillment timeline |
| `UNDERWRITE_DPDPA_DSR_GRIEVANCE_RESPONSE_DAYS` | No | `15` | Grievance response timeline |
| `UNDERWRITE_DPDPA_DPO_EMAIL` | No | `""` | Data Protection Officer email |
| `UNDERWRITE_DPDPA_DPO_PHONE` | No | `""` | Data Protection Officer phone |

---

## KFS (Key Fact Statement — India)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_KFS_COOLING_OFF_DAYS` | No | `3` | Free-look period after KFS issuance per RBI DLG |
| `UNDERWRITE_KFS_DISCLOSURE_VERSION` | No | `1.0` | KFS template version |

---

## Notification Service

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NOTIFICATION_EMAIL_ENABLED` | No | `false` | Enable email dispatch via SES |
| `NOTIFICATION_SMS_ENABLED` | No | `false` | Enable SMS dispatch via Twilio |
| `NOTIFICATION_EMAIL_SENDER` | No | `noreply@underwrite.local` | SES sender address |
| `AWS_REGION` | No | `""` | AWS region for SES (leave empty to log instead of sending) |
| `TWILIO_ACCOUNT_SID` | No | `""` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | No | `""` | Twilio auth token |
| `TWILIO_FROM_NUMBER` | No | `""` | Twilio SMS source phone number |

---

## Testing

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UNDERWRITE_TEST_PG_DSN` | No | `""` | PostgreSQL DSN for integration tests |

---

## Boolean Coercion

When an environment variable maps to a `bool` field, the string is considered
`true` if it equals (case-insensitive) `1`, `true`, or `yes`. All other values
produce `false`.
