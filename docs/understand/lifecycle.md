# Indian lending lifecycle

The full Underwrite underwriting journey, end-to-end, against an
in-memory runtime. Twelve stages from onboarding to origination —
each one a nano-service, each transition a typed event, each event
carrying the runtime guarantees into the next stage.

This page is the primary mental model for the platform. The same
flow runs in production against Sqlite + OTLP + Vault; here it runs
in a single Python process with no broker, no cluster, no external
dependencies.

## The flow

<div class="uw-lifecycle" markdown>
<div class="uw-stage" markdown>
<span class="uw-stage__index">01</span>
<h3 class="uw-stage__name">Onboarding</h3>
<span class="uw-stage__meta">The mechanism service seeds capital and creates a sponsor → borrower pair. The first durable identity.</span>
<span class="uw-stage__event">seed.added · user.added</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">02</span>
<h3 class="uw-stage__name">Identity</h3>
<span class="uw-stage__meta">PAN and Aadhaar identifiers attach to the borrower. The identity service emits an attestable identity-registered event.</span>
<span class="uw-stage__event">identity.registered</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">03</span>
<h3 class="uw-stage__name">Consent</h3>
<span class="uw-stage__meta">DPDPA consent is recorded with a specific purpose (KYC verification). Withdrawable at any time. The consent service enforces re-consent on purpose change.</span>
<span class="uw-stage__event">consent.recorded</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">04</span>
<h3 class="uw-stage__name">KYC</h3>
<span class="uw-stage__meta">PAN format validation, Aadhaar Verhoeff checksum, AML risk score, CKYC registry trigger. Wire-protocol clients against NSDL / UIDAI / Karza.</span>
<span class="uw-stage__event">kyc.verified</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">05</span>
<h3 class="uw-stage__name">AML</h3>
<span class="uw-stage__meta">Sanctions screening, transaction pattern checks, risk scoring. AML clears or freezes; the runtime routes to the next stage or to the DLQ with a recorded error.</span>
<span class="uw-stage__event">aml.cleared · aml.flagged</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">06</span>
<h3 class="uw-stage__name">Credit bureau</h3>
<span class="uw-stage__meta">CIBIL / Experian / Equifax pull. The credit_bureau service emits a normalized credit_bureau.checked event regardless of which bureau responded.</span>
<span class="uw-stage__event">credit_bureau.checked</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">07</span>
<h3 class="uw-stage__name">Underwriting</h3>
<span class="uw-stage__meta">Rule engine + ML risk model evaluate the application against business rules. Approved, rejected, conditional, or escalated.</span>
<span class="uw-stage__event">underwriter.approved · underwriter.rejected</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">08</span>
<h3 class="uw-stage__name">Pricing</h3>
<span class="uw-stage__meta">RBI rate caps applied. All-in-cost APR (interest + fees + GST + insurance) computed. EMI, total interest, processing fee emitted.</span>
<span class="uw-stage__event">pricing.computed</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">09</span>
<h3 class="uw-stage__name">Compliance</h3>
<span class="uw-stage__meta">Cooling-off period enforced. Breach checks run. Compliance emits kfs.generated and gates the next stage.</span>
<span class="uw-stage__event">kfs.generated</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">10</span>
<h3 class="uw-stage__name">KFS</h3>
<span class="uw-stage__meta">Key Fact Statement issued to the borrower — a complete, versioned disclosure of every pricing and consent fact.</span>
<span class="uw-stage__event">kfs.generated</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">11</span>
<h3 class="uw-stage__name">Mandate</h3>
<span class="uw-stage__meta">e-NACH / UPI Autopay mandate collection. <em>Roadmap item — not yet wired to a partner.</em> When enabled, the razorpay service emits mandate events.</span>
<span class="uw-stage__event">razorpay.mandate.active (planned)</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">12</span>
<h3 class="uw-stage__name">Origination</h3>
<span class="uw-stage__meta">The mechanism service books the loan. The audit service persists a redacted copy. The NPA classifier starts watching. The lifecycle is complete.</span>
<span class="uw-stage__event">loan.originated</span>
</div>
</div>

## What the runtime adds at every transition

| Concern | Where it attaches | What it adds |
|---------|-------------------|--------------|
| Signing | `Core.emit` | Ed25519 over canonical bytes; deterministic across processes |
| Verification | `Core.dispatch` | Signature checked before handler runs |
| Idempotency | `Core.dispatch` | Duplicates dropped silently; cache bounded |
| Tracing | `Core.handle_event` | Span lifecycle, parent / child propagation |
| Metrics | `Core.handle_event` | Counters, timers, gauges per service and event type |
| Authz | `Core.dispatch` + `Core.emit` | Default-deny policy evaluation |
| DLQ | `LocalBus.dispatch` | Failed events captured with original error |
| Circuit breaking | `LocalBus.dispatch` | Per-subscriber breaker; OPEN after threshold |
| Saga coordination | `Orchestrator` | Multi-step workflows with compensating rollback |

These guarantees are not optional. Every `Core`-derived service
inherits them through the `dispatch` pipeline; there is no way for
a service to opt out, and no way for a service to write the
dispatch logic itself.

## Compliance responsibility by stage

| Stage | Responsibility |
|-------|----------------|
| Onboarding | KYC for the sponsor; sponsor authorization |
| Identity | Identity verification; re-attestation on key rotation |
| Consent | DPDPA consent validity; purpose binding; withdrawal |
| KYC | PAN format, Aadhaar Verhoeff, AML risk score |
| AML | Sanctions screening; PEP screening; transaction patterns |
| Credit bureau | Bureau response normalization; consent re-check |
| Underwriting | Business rules; model versioning; explainability |
| Pricing | RBI rate caps; all-in-cost APR disclosure |
| Compliance | Cooling-off; KFS issuance before disbursement |
| KFS | Complete disclosure; version pinning |
| Mandate | e-NACH / UPI Autopay consent; revocation handling |
| Origination | Audit ledger; NPA classifier activation |

## Visualizing the flow

```mermaid
sequenceDiagram
    participant B as Borrower
    participant M as mechanism
    participant ID as identity
    participant CO as consent
    participant KY as compliance
    participant CR as credit_bureau
    participant U as underwriter
    participant PR as pricing
    participant K as kfs
    participant AU as audit

    B->>M: add_user
    M->>AU: user.added
    B->>CO: record_consent
    CO->>AU: consent.recorded
    B->>KY: kyc_check
    KY->>AU: kyc.verified
    B->>CR: credit_check
    CR->>AU: credit_bureau.checked
    B->>U: evaluate
    U->>AU: underwriter.approved
    B->>PR: compute
    PR->>AU: pricing.computed
    B->>K: generate
    K->>AU: kfs.generated
    B->>M: originate
    M->>AU: loan.originated
```

Every event flows through `audit` — the persistent, PII-redacted
record of the run.

## See also

- [Architecture](architecture.md) — how the layers fit together.
- [Compliance](compliance.md) — the runtime defaults that encode each regulatory control.
- [Indian lending example](../start/examples/indian_lending.py) — the script this page describes.