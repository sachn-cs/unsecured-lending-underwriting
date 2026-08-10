# KYC Provider Integrations

This document describes the four KYC provider integrations that
land in v0.9. Each provider has a sandbox endpoint that can be
hit without credentials; production deployments set the partner
URL and load the partner credentials from the configured
`SecretsManager`.

## Configuration

```json
{
  "kyc_providers": {
    "pan_client_id": "...",
    "pan_client_secret": "...",
    "pan_api_base_url": "https://api.karza.in",
    "aadhaar_kua_id": "...",
    "aadhaar_kua_license_key": "...",
    "aadhaar_api_base_url": "https://www.uidai.gov.in",
    "cibil_partner_id": "...",
    "cibil_partner_key": "...",
    "cibil_api_base_url": "https://api.cibil.com",
    "ckyc_search_provider_id": "...",
    "ckyc_search_provider_key": "...",
    "ckyc_api_base_url": "https://search.ckycindia.in",
    "timeout_seconds": 30
  }
}
```

Secret-shaped fields (`*_secret`, `*_key`, `*_id`, `*_token`) are
never persisted in the config file — they are read from the
configured `SecretsManager` (Vault, AWS SM, or env) at startup.
`Configuration.to_dict()` redacts them, so `config.save()` cannot
leak them.

The following env vars opt the clients into their production
endpoints (sandbox by default):

- `UNDERWRITE_PAN_PRODUCTION=true` — point PAN at the live
  Karza/Signzy endpoint
- `UNDERWRITE_AADHAAR_PRODUCTION=true` — point Aadhaar at the
  UIDAI production KUA
- `UNDERWRITE_CIBIL_PRODUCTION=true` — point CIBIL at the
  partner production API
- `UNDERWRITE_CKYC_PRODUCTION=true` — point CKYC at the CERSAI
  production search endpoint

## Common surface

Every provider client extends `KycProvider` and exposes the same
two methods:

- `is_configured()` — returns `True` only when the client has
  the credentials it needs to call the real upstream API
- `verify(identifier, **kwargs)` — runs a verification and
  returns a `ProviderResult` carrying a `Verdict` and the
  provider's structured response

```python
from underwrite.services.kyc_providers import (
    PanVerificationClient,
    AadhaarEKycClient,
    CibilBureauClient,
    CkycSearchClient,
    Verdict,
    ProviderResult,
)
```

`Verdict` is one of:

- `Verdict.VERIFIED` — provider confirms the record
- `Verdict.NOT_FOUND` — no record at the provider
- `Verdict.MISMATCH` — input was malformed or didn't match
- `Verdict.AMBIGUOUS` — provider returned a borderline result
- `Verdict.REJECTED` — DPDPA consent missing or record invalid
- `Verdict.ERROR` — transport or upstream failure

Clients never raise on transport or upstream failure; they
return `Verdict.ERROR` with a descriptive message in the
`error` field and log the underlying exception with
`logger.exception(...)`.

## PAN (ITD / NSDL)

Endpoint: `POST {api_base_url}/v2/pan/verify`

Wire request:

```json
{
  "pan_number": "ABCDE1234F",
  "name": "John Doe",
  "dob": "1990-01-01",
  "consent": "Y"
}
```

Wire response:

```json
{
  "request_id": "...",
  "status": "VALID",
  "pan_status": "ACTIVE",
  "pan_type": "Individual",
  "first_name": "John",
  "last_name": "Doe",
  "aadhaar_seeding_status": "Y"
}
```

The request body is HMAC-SHA256 signed with `client_secret`;
the signature is sent in the `x-signature` header. The Karza
sandbox is the default; Signzy uses the same wire shape with a
different `api_base_url`.

## Aadhaar eKYC (UIDAI KUA)

Endpoint: `POST {api_base_url}/eKYC/v3/auth/`

Wire request:

```json
{
  "aadhaar_token": "123456789012",
  "otp": "123456",
  "consent": "Y",
  "purpose": "loan-origination"
}
```

Wire response (after the KUA SDK decrypts the auth XML):

```json
{
  "reference_id": "...",
  "status": "Y",
  "name": "John Doe",
  "dob": "1990-01-01",
  "gender": "M",
  "address": {...},
  "photo": "<base64>"
}
```

The base client hits the UIDAI staging endpoint as a shape
reference. Production deployments override
`_send_kyc_request` to plug in the KUA SDK
(`pyuid` / `okhota` / proprietary); the override should call
the KUA's PKI-encrypted transport, decrypt the auth XML, and
return the same `dict` shape.

## CIBIL consumer bureau pull

Endpoint: `POST {api_base_url}/v2/cibil/score`

Wire request:

```json
{
  "consumer_id": "...",
  "name": "John Doe",
  "dob": "1990-01-01",
  "pan": "ABCDE1234F",
  "address": {...},
  "consent": "Y"
}
```

Wire response:

```json
{
  "request_id": "...",
  "score": 750,
  "score_band": "Excellent",
  "tradelines": 5,
  "enquiries_last_30_days": 1,
  "defaults": []
}
```

The bureau score in `details["score"]` is an integer in the
300-900 range; values outside that range produce
`Verdict.AMBIGUOUS` rather than `Verdict.VERIFIED`.

## CKYC registry search (CERSAI)

Endpoint: `POST {api_base_url}/v1/ckyc/search`

Wire request:

```json
{
  "ckyc_number": "110000001234",
  "consent": "Y"
}
```

Wire response:

```json
{
  "request_id": "...",
  "ckyc_number": "110000001234",
  "name": "John Doe",
  "dob": "1990-01-01",
  "pan": "ABCDE1234F",
  "aadhaar_last4": "1234",
  "address": {...},
  "image_present": true,
  "kyc_status": "VERIFIED"
}
```

The `identifier_type` argument selects the search mode:
`"ckyc_number"`, `"pan"`, or `"aadhaar"`. Any other value
returns `Verdict.ERROR`.

## Service integration

The `compliance` and `credit_bureau` services consume the
configured providers via the runtime-injected `kyc_providers`
dict. Without a provider, both fall back to format-only
validation (the v0.8 behaviour); with a provider, the real
upstream call gates the service's KYC verdict.

```python
# Runtime auto-wiring — no application code required:
Runtime(
    config,  # has kyc_providers populated from Configuration
).register("compliance")
```

## Sandbox vs production

The four providers default to the public sandbox endpoints
because the sandbox is what the partner gives you for free
during integration. Production deployments set the matching
`UNDERWRITE_*_PRODUCTION=true` env var and set the
corresponding `*_api_base_url` to the partner's live endpoint.

The client itself does not switch endpoints automatically; the
URL is a runtime configuration value, and the production gate
is a separate flag. This is intentional: it lets a staging
deployment use the production partner URL against a partner
sandbox tenant, which is a different configuration from
"production with the partner's live API".
