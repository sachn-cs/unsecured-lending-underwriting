<!-- HERO ============================================================ -->
<section class="uw-hero" markdown>
<span class="uw-hero__eyebrow">Open-source lending infrastructure</span>

<h1 class="uw-hero__title">Build Indian lending systems on a hardened underwriting runtime.</h1>

<p class="uw-hero__lede">
Underwrite turns underwriting capabilities into composable nano-services communicating through typed, signed events. The runtime handles the cross-cutting operational concerns — authz, identity, idempotency, tracing, metrics, sagas, supervision, and dead-lettering — so a 50-line service can carry the guarantees of a regulated platform.
</p>

<div class="uw-hero__ctas" markdown>
<a href="start/" class="md-button md-button--primary">Get started</a>
<a href="understand/architecture/" class="md-button md-button--secondary">Explore the architecture</a>
</div>

<div class="uw-hero__links" markdown>
[GitHub](https://github.com/sachncs/underwrite) · [API reference](reference/) · [Quickstart](start/quickstart/)
</div>
</section>

<!-- TRUST STRIP ===================================================== -->
<div class="uw-trust" markdown>
<div class="uw-trust__grid" markdown>
<div class="uw-trust__item" markdown>
<span class="uw-trust__value">34</span>
<span class="uw-trust__label">nano-services</span>
</div>
<div class="uw-trust__item" markdown>
<span class="uw-trust__value">132</span>
<span class="uw-trust__label">event types</span>
</div>
<div class="uw-trust__item" markdown>
<span class="uw-trust__value">1,276+</span>
<span class="uw-trust__label">tests</span>
</div>
<div class="uw-trust__item" markdown>
<span class="uw-trust__value">Ed25519</span>
<span class="uw-trust__label">event signatures</span>
</div>
<div class="uw-trust__item" markdown>
<span class="uw-trust__value">RBI / DPDPA</span>
<span class="uw-trust__label">aligned defaults</span>
</div>
</div>
</div>

<!-- PILLARS =========================================================== -->
<section class="uw-section" id="runtime" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">The underwriting runtime</span>
<h2>Domain logic on top. Runtime guarantees underneath.</h2>
<p>The product is not the services — it is the runtime they run on. Underwrite is structured so that the four layers below are clearly separated: domain code expresses lending intent, the event runtime guarantees delivery, the control plane enforces policy, and the operational layer makes the system inspectable.</p>
</div>

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<div class="uw-card__icon" markdown>
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
</div>
<h3>Domain services</h3>
<p>KYC, AML, credit, pricing, compliance, consent, KFS, origination, and related workflows. These are the parts that change when a lender changes policy.</p>
<ul>
<li>34 wired nano-services</li>
<li>PAN, Aadhaar eKYC, CIBIL, CKYC integrations</li>
<li>RBI-aligned pricing and KFS</li>
</ul>
</div>

<div class="uw-card" markdown>
<div class="uw-card__icon" markdown>
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7 H17 M3 12 H21 M3 17 H13"/><circle cx="21" cy="12" r="1.6" fill="currentColor"/></svg>
</div>
<h3>Event runtime</h3>
<p>Typed events with Ed25519 attestation, idempotent dispatch, replay, and routing. The runtime decides <em>how</em> events flow; the services decide <em>what</em> they mean.</p>
<ul>
<li>132 typed event types</li>
<li>5-minute replay window</li>
<li>Bounded DLQ with deduplication</li>
</ul>
</div>

<div class="uw-card" markdown>
<div class="uw-card__icon" markdown>
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 L4 6 V12 C4 17 7.5 21 12 22 C16.5 21 20 17 20 12 V6 Z"/><path d="M9 12 L11 14 L15 10"/></svg>
</div>
<h3>Control plane</h3>
<p>Authorization, identity, saga coordination, supervision, and failure handling. Policies and rules live here, so individual services stay focused on domain logic.</p>
<ul>
<li>Default-deny access control</li>
<li>Saga orchestrator with rollback</li>
<li>Per-handler circuit breaking</li>
</ul>
</div>

<div class="uw-card" markdown>
<div class="uw-card__icon" markdown>
<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9 H21"/><circle cx="7" cy="6" r="0.6" fill="currentColor"/><circle cx="10" cy="6" r="0.6" fill="currentColor"/><path d="M7 14 L10 14 M7 17 L13 17"/></svg>
</div>
<h3>Operational layer</h3>
<p>Metrics, health, readiness, tracing, persistence, and deployable infrastructure. The runtime exports signals in formats operators already use.</p>
<ul>
<li>Prometheus metrics on <code>/metrics</code></li>
<li>OpenTelemetry tracing (console / OTLP)</li>
<li>Sqlite store, PII-redacted audit ledger</li>
</ul>
</div>
</div>
</section>

<!-- YOU WRITE THE DOMAIN ============================================ -->
<section class="uw-section uw-section--alt" id="you-write-the-domain" markdown>
<div class="uw-principle" markdown>
<div class="uw-principle__inner" markdown>
<div markdown>
<span class="uw-eyebrow" style="color: rgba(250,248,245,0.6);">The brand idea</span>
<h2>You define the lending domain. Underwrite provides the runtime.</h2>
<p>Complex financial infrastructure should not have to be reinvented inside every service. A Underwrite service looks like a function on an event; everything else is provided automatically and uniformly across the system.</p>
<p>The runtime guarantees are not a feature checklist — they are the product. Authorization, signing, idempotency, tracing, metrics, sagas, supervision, and the dead-letter queue arrive by construction, not by convention.</p>
</div>

<div markdown>
<div class="uw-runtime-stack" markdown>
<span class="uw-domain">YOUR CODE</span>
<span class="uw-runtime-arrow">  ↓</span>
<span class="uw-domain">handle(event)</span>

<span class="uw-runtime-arrow">UNDERWRITE RUNTIME</span>
├── <strong>authz</strong>
├── <strong>identity</strong>
├── <strong>signatures</strong>
├── <strong>idempotency</strong>
├── <strong>tracing</strong>
├── <strong>metrics</strong>
├── <strong>saga coordination</strong>
├── <strong>DLQ</strong>
└── <strong>supervision</strong>
</div>
</div>
</div>
</section>

<!-- LIFECYCLE ======================================================= -->
<section class="uw-section" id="lifecycle" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Indian lending lifecycle</span>
<h2>One borrower, twelve stages, every guarantee carried.</h2>
<p>The full underwriting flow runs end-to-end against an in-memory store. Each stage is a nano-service, each transition is a typed event, and each event carries the runtime's guarantees — signatures, audit, replay — into the next.</p>
</div>

<div class="uw-lifecycle" markdown>
<div class="uw-stage" markdown>
<span class="uw-stage__index">01</span>
<h3 class="uw-stage__name">Onboarding</h3>
<span class="uw-stage__meta">Borrower + sponsor pair created</span>
<span class="uw-stage__event">mechanism.user.added</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">02</span>
<h3 class="uw-stage__name">Identity</h3>
<span class="uw-stage__meta">PAN + Aadhaar attached to user</span>
<span class="uw-stage__event">identity.registered</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">03</span>
<h3 class="uw-stage__name">Consent</h3>
<span class="uw-stage__meta">DPDPA consent recorded</span>
<span class="uw-stage__event">consent.recorded</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">04</span>
<h3 class="uw-stage__name">KYC</h3>
<span class="uw-stage__meta">PAN validated, Aadhaar Verhoeff</span>
<span class="uw-stage__event">kyc.verified</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">05</span>
<h3 class="uw-stage__name">AML</h3>
<span class="uw-stage__meta">Risk score + sanctions screening</span>
<span class="uw-stage__event">aml.cleared</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">06</span>
<h3 class="uw-stage__name">Credit bureau</h3>
<span class="uw-stage__meta">CIBIL / Experian / Equifax pull</span>
<span class="uw-stage__event">credit_bureau.checked</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">07</span>
<h3 class="uw-stage__name">Underwriting</h3>
<span class="uw-stage__meta">Rule engine + risk model</span>
<span class="uw-stage__event">underwriter.approved</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">08</span>
<h3 class="uw-stage__name">Pricing</h3>
<span class="uw-stage__meta">RBI rate caps + all-in-cost APR</span>
<span class="uw-stage__event">pricing.computed</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">09</span>
<h3 class="uw-stage__name">Compliance</h3>
<span class="uw-stage__meta">Cooling-off + breach checks</span>
<span class="uw-stage__event">kfs.generated</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">10</span>
<h3 class="uw-stage__name">KFS</h3>
<span class="uw-stage__meta">Key Fact Statement issued</span>
<span class="uw-stage__event">kfs.generated</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">11</span>
<h3 class="uw-stage__name">Mandate</h3>
<span class="uw-stage__meta">e-NACH / UPI Autopay (v1.0)</span>
<span class="uw-stage__event">razorpay.mandate.active</span>
</div>

<div class="uw-stage" markdown>
<span class="uw-stage__index">12</span>
<h3 class="uw-stage__name">Origination</h3>
<span class="uw-stage__meta">Loan booked, audit persisted</span>
<span class="uw-stage__event">loan.originated</span>
</div>
</div>
</section>

<!-- COMPLIANCE BY DEFAULT ========================================== -->
<section class="uw-section uw-section--alt" id="compliance" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Compliance by default</span>
<h2>Regulatory concerns, encoded into the runtime.</h2>
<p>Underwrite's defaults are aligned with RBI Digital Lending Guidelines and DPDPA 2023 — rate caps, all-in-cost APR, penal-interest limits, KFS cooling-off, consent lifecycle, DSR fulfillment, breach notification, and auto-purge. They are <em>properties of the runtime</em>, not conventions every team has to remember to apply.</p>
<p class="uw-lede">Use the precise language: <strong>RBI / DPDPA-aligned defaults</strong>. We do not claim regulatory certification; we publish the configuration and code that encode the controls.</p>
</div>

<div class="grid grid-3" markdown>
<div class="uw-card" markdown>
<h3>Rate caps</h3>
<p>Personal loan, education loan, and consumption-loan caps per RBI norms. The pricing service refuses to compute outside the band.</p>
</div>

<div class="uw-card" markdown>
<h3>All-in-cost APR</h3>
<p>APR includes interest, processing fees, GST, and insurance — not just headline interest. The pricing service emits it as a first-class field.</p>
</div>

<div class="uw-card" markdown>
<h3>Penal-interest cap</h3>
<p>Penal interest is bounded as a function of the outstanding principal; the pricing service enforces the cap on every compute.</p>
</div>

<div class="uw-card" markdown>
<h3>KFS cooling-off</h3>
<p>Key Fact Statements are issued before disbursement. The KFS service enforces a cooling-off period between issuance and loan booking.</p>
</div>

<div class="uw-card" markdown>
<h3>Consent lifecycle</h3>
<p>DPDPA consent is recorded with purpose, validity, and withdrawal. The consent service enforces re-consent when the purpose changes.</p>
</div>

<div class="uw-card" markdown>
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
</div>
</section>

<!-- PROVABLE EVENT HISTORY ========================================= -->
<section class="uw-section" id="security" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Provable event history</span>
<h2>Every event is signed. Every signature is verifiable. Every record is auditable.</h2>
<p>An event moves through the runtime as a structured, attestable record. The same bytes that are signed on the publisher are verified by every subscriber, persisted by the audit service, and exposed for replay by the DLQ. The result is an event history that holds up to external review.</p>
</div>

<div class="uw-eventflow" markdown>
<div class="uw-eventflow__node">create</div>
<div class="uw-eventflow__node">sign</div>
<div class="uw-eventflow__node">publish</div>
<div class="uw-eventflow__node">handle</div>
<div class="uw-eventflow__node">persist</div>
<div class="uw-eventflow__node">audit</div>
<div class="uw-eventflow__node">replay</div>
</div>

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<h3>Ed25519 signatures</h3>
<p>Every event carries an Ed25519 signature over the canonical signing bytes — <code>event_id | timestamp | event_type | source | payload</code>. A holder of one trusted key cannot re-stamp an event under another service id or replay an old event outside the configured window.</p>
</div>

<div class="uw-card" markdown>
<h3>Replay window</h3>
<p>A configurable window (default 5 minutes) bounds the lifetime of a signature. Old captures cannot be re-broadcast. Operators tighten the window for high-risk flows and disable it for trusted backplanes.</p>
</div>

<div class="uw-card" markdown>
<h3>PII-redacted audit</h3>
<p>The audit service persists every event after redacting PAN, Aadhaar, and other token-matched identifiers. The same redaction applies to the DLQ and the Prometheus exporter.</p>
</div>

<div class="uw-card" markdown>
<h3>Deterministic records</h3>
<p>Canonical signing bytes use sorted JSON keys, strict JSON serialization (no <code>default=str</code> coercion), and an event-id generated from a UUIDv4. Two processes on different Python versions produce the same signature for the same event.</p>
</div>
</div>
</section>

<!-- ARCHITECTURE =================================================== -->
<section class="uw-section uw-section--alt" id="architecture-overview" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Architecture</span>
<h2>A small core, surrounded by domain services and operational infrastructure.</h2>
<p>Domain services express lending intent. The Underwrite core enforces the guarantees. The infrastructure layer provides the building blocks that operators already trust — Sqlite, Prometheus, OTLP, Vault, AWS.</p>
</div>

<div class="uw-architecture" markdown>
<svg viewBox="0 0 880 360" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Architecture diagram">
<defs>
<style>
.layer-label { font-family: "JetBrains Mono", "IBM Plex Mono", monospace; font-size: 11px; font-weight: 600; letter-spacing: 0.16em; fill: #6B7280; }
.cell { fill: #FAF8F5; stroke: #E8E4DC; stroke-width: 1; }
.cell-text { font-family: "Inter", "Helvetica Neue", sans-serif; font-size: 13px; font-weight: 500; fill: #0A0E14; }
.cell-sub { font-family: "JetBrains Mono", monospace; font-size: 11px; fill: #6B7280; }
.core-cell { fill: #0A0E14; }
.core-cell-text { font-family: "Inter", sans-serif; font-size: 14px; font-weight: 600; fill: #FAF8F5; }
.core-cell-sub { font-family: "JetBrains Mono", monospace; font-size: 11px; fill: rgba(250,248,245,0.65); }
.infra-cell { fill: #DCE6FF; stroke: #2F6BFF; stroke-width: 1; }
.infra-text { font-family: "Inter", sans-serif; font-size: 13px; font-weight: 600; fill: #1B49C7; }
.arrow { stroke: #6B7280; stroke-width: 1.5; fill: none; marker-end: url(#uw-arrow); }
.event-label { font-family: "JetBrains Mono", monospace; font-size: 11px; fill: #1B49C7; letter-spacing: 0.06em; }
</style>
<marker id="uw-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M 0 0 L 10 5 L 0 10 z" fill="#6B7280" />
</marker>
</defs>

<text x="40" y="32" class="layer-label">APPLICATION DOMAIN</text>
<g>
<rect class="cell" x="40"  y="48" width="120" height="60" rx="8" />
<text class="cell-text"    x="100" y="78" text-anchor="middle">KYC</text>
<text class="cell-sub"     x="100" y="96" text-anchor="middle">services/kyc</text>

<rect class="cell" x="180" y="48" width="120" height="60" rx="8" />
<text class="cell-text"    x="240" y="78" text-anchor="middle">AML</text>
<text class="cell-sub"     x="240" y="96" text-anchor="middle">services/aml</text>

<rect class="cell" x="320" y="48" width="120" height="60" rx="8" />
<text class="cell-text"    x="380" y="78" text-anchor="middle">Credit</text>
<text class="cell-sub"     x="380" y="96" text-anchor="middle">services/credit</text>

<rect class="cell" x="460" y="48" width="120" height="60" rx="8" />
<text class="cell-text"    x="520" y="78" text-anchor="middle">Pricing</text>
<text class="cell-sub"     x="520" y="96" text-anchor="middle">services/pricing</text>

<rect class="cell" x="600" y="48" width="120" height="60" rx="8" />
<text class="cell-text"    x="660" y="78" text-anchor="middle">KFS</text>
<text class="cell-sub"     x="660" y="96" text-anchor="middle">services/kfs</text>
</g>

<text x="40" y="148" class="layer-label">TYPED EVENTS</text>
<line x1="100" y1="108" x2="100" y2="148" class="arrow" />
<line x1="240" y1="108" x2="240" y2="148" class="arrow" />
<line x1="380" y1="108" x2="380" y2="148" class="arrow" />
<line x1="520" y1="108" x2="520" y2="148" class="arrow" />
<line x1="660" y1="108" x2="660" y2="148" class="arrow" />
<text x="440" y="142" class="event-label" text-anchor="middle">kyc.verified · aml.cleared · pricing.computed · kfs.generated</text>

<text x="40" y="180" class="layer-label">UNDERWRITE CORE</text>
<rect class="core-cell" x="40" y="196" width="800" height="84" rx="10" />
<g>
<text class="core-cell-text" x="100" y="222" text-anchor="middle">Authz</text>
<text class="core-cell-sub"  x="100" y="240" text-anchor="middle">policy engine</text>
<text class="core-cell-text" x="240" y="222" text-anchor="middle">Identity</text>
<text class="core-cell-sub"  x="240" y="240" text-anchor="middle">Ed25519 keys</text>
<text class="core-cell-text" x="380" y="222" text-anchor="middle">Idempotency</text>
<text class="core-cell-sub"  x="380" y="240" text-anchor="middle">dedup guard</text>
<text class="core-cell-text" x="520" y="222" text-anchor="middle">Supervisor</text>
<text class="core-cell-sub"  x="520" y="240" text-anchor="middle">auto-restart</text>
<text class="core-cell-text" x="660" y="222" text-anchor="middle">Sagas</text>
<text class="core-cell-sub"  x="660" y="240" text-anchor="middle">+ Circuit breaking</text>
<text class="core-cell-text" x="800" y="222" text-anchor="middle">DLQ</text>
<text class="core-cell-sub"  x="800" y="240" text-anchor="middle">+ bounded buffer</text>
</g>

<text x="40" y="304" class="layer-label">INFRASTRUCTURE</text>
<g>
<rect class="infra-cell" x="40"  y="316" width="180" height="32" rx="6" />
<text class="infra-text" x="130" y="338" text-anchor="middle">Store · Sqlite</text>

<rect class="infra-cell" x="240" y="316" width="180" height="32" rx="6" />
<text class="infra-text" x="330" y="338" text-anchor="middle">Metrics · Prometheus</text>

<rect class="infra-cell" x="440" y="316" width="180" height="32" rx="6" />
<text class="infra-text" x="530" y="338" text-anchor="middle">Tracing · OTLP</text>

<rect class="infra-cell" x="640" y="316" width="200" height="32" rx="6" />
<text class="infra-text" x="740" y="338" text-anchor="middle">Secrets · Vault / AWS</text>
</g>
</svg>
</div>

<p style="margin-top: 1.5rem;">The full architecture — including the layered rationale, event lifecycle, and runtime injection points — lives on the <a href="understand/architecture/">architecture page</a>.</p>
</section>

<!-- DEVELOPER EXPERIENCE =========================================== -->
<section class="uw-section" id="developer-experience" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Developer experience</span>
<h2>From zero to underwriting workflow.</h2>
<p>Despite the runtime depth, the developer experience is short. Six steps and you have a regulated-grade event flow running locally — no broker, no cluster, no external services required.</p>
</div>

<div class="uw-eventflow" markdown>
<div class="uw-eventflow__node">pip install</div>
<div class="uw-eventflow__node">Runtime()</div>
<div class="uw-eventflow__node">define service</div>
<div class="uw-eventflow__node">handle event</div>
<div class="uw-eventflow__node">compose services</div>
<div class="uw-eventflow__node">run lending lifecycle</div>
</div>

<p>The smallest useful example:</p>

<div class="uw-terminal" markdown>
<span class="uw-prompt">$</span> <span class="uw-cmd">git clone https://github.com/sachncs/underwrite.git</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">cd underwrite && ./setup.sh</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">source .venv/bin/activate</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">python docs/examples/indian_lending.py</span>
<span class="uw-out">seed.added           hdfc-bank seeded ₹10,000,000</span>
<span class="uw-out">user.added           priya-sharma sponsored by hdfc-bank (₹500,000)</span>
<span class="uw-out">consent.recorded     kyc_verification consent granted</span>
<span class="uw-out">kyc.verified         PAN + Aadhaar valid</span>
<span class="uw-out">aml.cleared          Risk score 1 — cleared</span>
<span class="uw-out">ckyc.verify          Registry lookup initiated</span>
<span class="uw-out">credit_bureau.checked Score: 720 (CIBIL)</span>
<span class="uw-out">pricing.computed     ₹300K @ 28% APR, EMI ₹16,543/month</span>
<span class="uw-out">kfs.generated        Key Fact Statement v1.0 issued</span>
<span class="uw-out">loan.originated      ₹300,000 personal loan approved</span>
<span class="uw-out">dlq.size             0</span>
</div>
</section>

<!-- QUICKSTART ====================================================== -->
<section class="uw-section uw-section--alt" id="quickstart" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Quickstart</span>
<h2>Install on the left. Run the Indian scenario on the right.</h2>
<p>The setup script creates a virtualenv, installs editable + dev extras, and configures pre-commit hooks. The Indian lending example exercises the full event-driven workflow against an in-memory store — a regulator-aligned origination in a fraction of a second.</p>
</div>

<div class="grid grid-2" markdown>
<div markdown>
<h3 style="margin-top:0;">1. Install and initialize</h3>
<div class="uw-terminal" markdown>
<span class="uw-comment"># clone and bootstrap</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">git clone https://github.com/sachncs/underwrite.git</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">cd underwrite && ./setup.sh</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">source .venv/bin/activate</span>

<span class="uw-comment"># verify</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">pytest tests/ -q</span>
<span class="uw-out">1276 passed in 6.2s</span>

<span class="uw-comment"># initialize a config</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">underwrite init</span>
</div>
</div>

<div markdown>
<h3 style="margin-top:0;">2. Run the Indian scenario</h3>
<div class="uw-terminal" markdown>
<span class="uw-comment"># start the runtime services</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">underwrite run mechanism audit pricing compliance</span>

<span class="uw-comment"># exercise the full borrower flow</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">python docs/examples/indian_lending.py</span>
<span class="uw-out">loan.originated  ₹300,000 personal loan approved</span>

<span class="uw-comment"># inspect the audit trail</span>
<span class="uw-prompt">$</span> <span class="uw-cmd">underwrite health</span>
</div>

<p style="margin-top:1rem;">Underneath, the run drives the pipeline:</p>

<div class="uw-eventflow" style="grid-template-columns: repeat(4, 1fr);" markdown>
<div class="uw-eventflow__node">PAN</div>
<div class="uw-eventflow__node">Aadhaar</div>
<div class="uw-eventflow__node">Consent</div>
<div class="uw-eventflow__node">KYC/AML</div>
<div class="uw-eventflow__node">CIBIL/CKYC</div>
<div class="uw-eventflow__node">Pricing</div>
<div class="uw-eventflow__node">KFS</div>
<div class="uw-eventflow__node">Origination</div>
</div>
</div>
</div>

<p style="margin-top:1.5rem;">The complete annotated walkthrough lives on the <a href="start/quickstart/">quickstart page</a>.</p>
</section>

<!-- INFRASTRUCTURE FLEXIBILITY ===================================== -->
<section class="uw-section" id="infrastructure" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Infrastructure flexibility</span>
<h2>Start inside one Python process. Replace infrastructure as your system grows.</h2>
<p>Underwrite begins as a single Python process with Sqlite and an in-process bus. The same code runs in production against OTLP tracing, Vault-backed secrets, and multi-arch container images. There is no "lite" version and no "production" version — the runtime is the same; the backends swap.</p>
</div>

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<h3>Local</h3>
<ul>
<li>SQLite store (file or <code>:memory:</code>)</li>
<li>In-process event bus</li>
<li>Console tracing</li>
<li>Env-var secrets</li>
<li>Single process, in-memory DLQ</li>
</ul>
</div>

<div class="uw-card" markdown>
<h3>Production</h3>
<ul>
<li>Sqlite + optional WAL volume mounts</li>
<li>Pluggable bus: Modal, SQS, in-process</li>
<li>OTLP tracing to a collector</li>
<li>Vault / AWS secrets managers</li>
<li>Multi-arch Docker image (amd64 + arm64)</li>
<li>DLQ with store-backed durability</li>
</ul>
</div>
</div>

<p style="margin-top: 1.5rem;">The default extras (<code>[risk]</code>, <code>[serve]</code>, <code>[otlp]</code>, <code>[vault]</code>, <code>[aws]</code>, <code>[gcs]</code>, <code>[modal]</code>) install only the dependencies you opt into. The core stays minimal.</p>
</section>

<!-- OPERATOR EXPERIENCE ============================================ -->
<section class="uw-section uw-section--alt" id="operators" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Operator experience</span>
<h2>Observability as a product surface, not an afterthought.</h2>
<p>The runtime emits health, readiness, metrics, traces, DLQ state, and saga state in formats operators already use. No proprietary dashboards; no fake monitoring screenshots; no claims about "visibility" without surfaces.</p>
</div>

<div class="grid grid-3" markdown>
<div class="uw-card" markdown>
<h3>Health and readiness</h3>
<p><code>/healthz</code> (liveness) and <code>/readyz</code> (readiness, including store ping) are wired for Kubernetes probes. <code>/v1/health</code> reports every subsystem.</p>
</div>

<div class="uw-card" markdown>
<h3>Metrics</h3>
<p>Prometheus metrics on the conventional <code>/metrics</code> path with <code>/v1/metrics</code> as a versioned alias. Counters, timers, gauges; per-handler latency and per-event-type counts.</p>
</div>

<div class="uw-card" markdown>
<h3>Tracing</h3>
<p>OpenTelemetry spans for every dispatch. Console by default, OTLP via the <code>[otlp]</code> extra. Parent / child propagation across events.</p>
</div>

<div class="uw-card" markdown>
<h3>DLQ replay</h3>
<p>The dead-letter queue is bounded, deduplicated, and replayable. The <code>underwrite dlq --replay</code> command replays the entire queue back onto the bus.</p>
</div>

<div class="uw-card" markdown>
<h3>Saga rollback</h3>
<p>Multi-step workflows carry compensating actions. The orchestrator emits <code>saga.rolled_back</code> with the failed step; the runtime drives compensation.</p>
</div>

<div class="uw-card" markdown>
<h3>Release process</h3>
<p>Tag-driven publishing with reproducible builds, signed wheels, multi-arch images, and a documented release checklist. See <a href="operate/release-process/">release process</a>.</p>
</div>
</div>
</section>

<!-- PRODUCT STATUS ================================================= -->
<section class="uw-section" id="status" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Product status</span>
<h2>What exists today, and what is still ahead.</h2>
</div>

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem;">
<span class="uw-status">v0.9 — shipped</span>
</div>
<h3>What v0.9 ships</h3>
<ul>
<li>34 wired nano-services, 132 event types</li>
<li>Real KYC wire-protocol clients (PAN, Aadhaar, CIBIL, CKYC)</li>
<li>Ed25519 event signatures with replay window</li>
<li>Default-deny authz with policy file</li>
<li>Bounded DLQ with deduplication</li>
<li>PII-redacted audit ledger</li>
<li>Prometheus metrics, OpenTelemetry tracing</li>
<li>Production Docker image (multi-stage, non-root)</li>
<li>Full CI gate suite (mypy, ruff, bandit, pip-audit, TruffleHog)</li>
</ul>
</div>

<div class="uw-card" markdown>
<div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.5rem;">
<span class="uw-status" style="background: var(--uw-paper);">v1.0 — future</span>
</div>
<h3>What belongs to v1.0</h3>
<ul>
<li>Live KYC partner-sandbox validation</li>
<li>e-NACH / UPI Autopay mandate collection</li>
<li>Full RBAC beyond the basic policy file</li>
<li>Pre-built multi-arch Docker images published to GHCR</li>
<li>Production on-call runbook (Ed25519 key rotation, DLQ replay, breach notification)</li>
<li>Video KYC integration (Digilocker, NSDL eSign)</li>
<li>Saga persistence via the Store backend (in-memory today)</li>
<li>OpenAPI 3.1 spec generated from the FastAPI surface</li>
</ul>
</div>
</div>

<p style="margin-top:1.5rem;">A Helm chart is <strong>not</strong> planned. Deploy the multi-arch container directly or with a project-specific compose / kustomize overlay. Full roadmap: <a href="project/roadmap/">ROADMAP.md</a>.</p>
</section>

<!-- CONVERSION PATHS =============================================== -->
<section class="uw-section uw-section--alt" id="who-this-is-for" markdown>
<div class="uw-section__head" markdown>
<span class="uw-eyebrow">Where to start</span>
<h2>Five visitors, five paths.</h2>
<p>Each path leads to real documentation, not a marketing dead end.</p>
</div>

<div class="uw-personas" markdown>
<div class="uw-persona" markdown>
<span class="uw-persona__role">Engineer</span>
<h3 class="uw-persona__name">Get started</h3>
<a href="start/" class="uw-persona__link">Install and run your first service</a>
</div>

<div class="uw-persona" markdown>
<span class="uw-persona__role">Architect</span>
<h3 class="uw-persona__name">View architecture</h3>
<a href="understand/architecture/" class="uw-persona__link">Runtime, events, control plane</a>
</div>

<div class="uw-persona" markdown>
<span class="uw-persona__role">Risk &amp; compliance</span>
<h3 class="uw-persona__name">Explore compliance</h3>
<a href="understand/compliance/" class="uw-persona__link">RBI / DPDPA-aligned defaults</a>
</div>

<div class="uw-persona" markdown>
<span class="uw-persona__role">Researcher</span>
<h3 class="uw-persona__name">Inspect implementation</h3>
<a href="https://github.com/sachncs/underwrite" class="uw-persona__link">Source on GitHub</a>
</div>

<div class="uw-persona" markdown>
<span class="uw-persona__role">Contributor</span>
<h3 class="uw-persona__name">Contribute</h3>
<a href="project/contributing/" class="uw-persona__link">Branching, gates, PR process</a>
</div>
</div>
</section>

---

<div class="uw-lede" style="margin: 3rem auto; text-align: center; max-width: 60ch;" markdown>
**Underwrite** is open source under the MIT license. Inspect the code, run the runtime, deploy it in your own infrastructure. Financial infrastructure you can read, modify, and own.
</div>