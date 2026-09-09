# Compliance

Underwrite's regulatory posture is **aligned with RBI Digital
Lending Guidelines and DPDPA 2023**, encoded as runtime defaults.
This page describes what those defaults do, where they live in the
code, and how to verify them.

!!! note "Language we use"
    We say **RBI / DPDPA-aligned defaults** — not "compliant".
    Compliance is a regulatory determination; what we ship is a
    runtime whose defaults encode the controls a regulated lender
    is expected to operate. Final compliance is your responsibility
    and your regulator's.

## What the runtime defaults to

<div class="grid grid-3" markdown>
<div class="uw-card" markdown>
<h3>Rate caps</h3>
<p>Personal loan, education loan, and consumption-loan caps per RBI norms. The pricing service refuses to compute outside the band. Source: <code>underwrite.services.pricing</code>.</p>
</div>

<div class="uw-card" markdown>
<h3>All-in-cost APR</h3>
<p>APR includes interest, processing fees, GST, and insurance — not just headline interest. The pricing service emits it as a first-class field on <code>pricing.computed</code>.</p>
</div>

<div class="uw-card" markdown>
<h3>Penal-interest cap</h3>
<p>Penal interest is bounded as a function of the outstanding principal. The pricing service enforces the cap on every compute.</p>
</div>

<div class="uw-card" markdown">
<h3>KFS cooling-off</h3>
<p>Key Fact Statements are issued before disbursement. The KFS service enforces a cooling-off period between issuance and loan booking.</p>
</div>

<div class="uw-card" markdown>
<h3>Consent lifecycle</h3>
<p>DPDPA consent is recorded with purpose, validity, and withdrawal. The consent service enforces re-consent when the purpose changes.</p>
</div>

<div class="uw-card" markdown">
<h3>DSR fulfillment</h3>
<p>Data Subject Rights requests are tracked end-to-end with response-time SLAs. The DSR service emits breach events on SLA violations.</p>
</div>

<div class="uw-card" markdown>
<h3>Breach notification</h3>
<p>Breach detection, classification, and notification are wired through the runtime. Notifications fire within configured windows.</p>
</div>

<div class="uw-card" markdown>
<h3>Auto-purge</h3>
<p>PII-bearing records are purged at the configured retention horizon. The audit service redacts PII before export.</p>
</div>

<div class="uw-card" markdown>
<h3>Penal interest accrual</h3>
<p>Penal interest is calculated daily and capped monthly. The accrual rate is configurable per product.</p>
</div>
</div>

## Where the controls live in the code

| Control | Module | Enforcement point |
|---------|--------|-------------------|
| Rate caps | `underwrite/services/pricing.py` | `compute()` rejects amounts above the cap |
| APR math | `underwrite/services/pricing.py` | Includes fees + GST in the APR field |
| Penal-interest cap | `underwrite/services/pricing.py` | `compute_penal_interest()` clamps to the cap |
| KFS cooling-off | `underwrite/services/kfs.py` | Refuses generation outside the cooling-off window |
| Consent recording | `underwrite/services/consent.py` | `record()` validates purpose, expiry, withdrawal |
| Consent withdrawal | `underwrite/services/consent.py` | `withdraw()` revokes downstream access |
| DSR fulfillment | `underwrite/services/dsr.py` | Tracks request, fires `dsr.fulfilled` or breach |
| Breach notification | `underwrite/services/` | Emits `breach.detected` then `breach.notified` |
| Auto-purge | `underwrite/services/audit.py` | PII redacted before persistence |

## How to verify

The pricing defaults ship in `underwrite/config.py` as `PricingConfig`
fields. Override them in your environment to match your regulator's
view of your product:

```yaml
pricing:
  personal_loan_rate_cap: 0.28
  penal_interest_cap: 0.24
  education_loan_rate_cap: 0.16
  consumption_loan_rate_cap: 0.36
```

Run the pricing tests to verify your overrides:

```bash
pytest tests/test_pricing.py -v
```

Tests assert that the pricing service refuses to compute outside the
configured band, and that the emitted `pricing.computed` event
includes every disclosure field the regulator requires.

## What we do not claim

- **Regulatory certification.** We are not a regulated entity and
  do not claim to be. The runtime encodes controls; you operate
  them and your regulator audits them.
- **Legal advice.** The MIT license and the project README are
  explicit: this is not legal advice. Consult a qualified attorney
  before deploying in a regulated environment.
- **Liability for partner responses.** The wire-protocol clients
  are sandbox-shaped and must be credentialed against a real
  partner before they emit verified responses.

## Compliance as a runtime concern

The way compliance shows up in Underwrite is structural rather than
advisory. There is no "compliance checklist" you tick off; there
are runtime defaults that refuse to do the wrong thing.

- The pricing service will not produce a loan quote outside the
  RBI rate cap.
- The KFS service will not generate a statement during the
  cooling-off window.
- The consent service will not allow a service to act on data
  whose purpose was withdrawn.
- The audit service will not persist PII that has not been
  redacted.

These are not policy decisions encoded in configuration files that
operators can silently disable. They are the default behavior of
the runtime.

## What v0.9 ships vs what v1.0 will add

| v0.9 (shipped) | v1.0 (roadmap) |
|-----------------|-----------------|
| Rate caps, APR math, penal-interest cap | Live KYC partner-sandbox validation |
| KFS cooling-off | e-NACH / UPI Autopay mandate collection |
| Consent lifecycle, DSR fulfillment | Full RBAC beyond the policy file |
| Breach notification | Pre-built multi-arch images |
| PII redaction | Production on-call runbook |
| Audit ledger | Video KYC integration (Digilocker, NSDL eSign) |

The v0.9 controls are operational and tested. The v1.0 items are
tracked in [ROADMAP](../project/roadmap.md).

## See also

- [Indian lending lifecycle](lifecycle.md) — how the controls thread through the twelve-stage flow.
- [Security](security.md) — the audit and signature posture that gives compliance teeth.
- [Architecture](architecture.md) — where the controls live in the layered design.