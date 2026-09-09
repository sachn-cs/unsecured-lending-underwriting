# Underwrite

<div class="uw-hero" markdown>
# Build Indian retail-lending software on a hardened event-driven runtime.

Underwrite is a **nano-service platform** for delegated underwriting of unsecured retail loans in India. 34 nano-services communicate through typed, Ed25519-signed events on an in-process bus. Cross-cutting concerns — authz, tracing, metrics, idempotency, sagas, DLQ, circuit breaking — are injected by the runtime, not inherited.

<p>
  <a href="getting-started/" class="md-button md-button--primary">Get started</a>
  <a href="QUICKSTART/" class="md-button md-button--secondary">Try the Indian scenario</a>
  <a href="https://github.com/sachncs/underwrite"><span class="uw-pill">github.com/sachncs/underwrite</span></a>
</p>
</div>

## At a glance

<div class="uw-stats" markdown>
<div class="uw-stat" markdown>
<p class="uw-stat-value">34</p>
<p class="uw-stat-label">Wired nano-services</p>
</div>
<div class="uw-stat" markdown>
<p class="uw-stat-value">132</p>
<p class="uw-stat-label">Typed event types</p>
</div>
<div class="uw-stat" markdown>
<p class="uw-stat-value">~1276</p>
<p class="uw-stat-label">Tests across 72 files</p>
</div>
<div class="uw-stat" markdown>
<p class="uw-stat-value">RBI · DPDPA</p>
<p class="uw-stat-label">Aligned defaults</p>
</div>
</div>

## Why Underwrite

<div class="uw-features" markdown>
<div class="uw-feature" markdown>
<h3>Compliance by default</h3>
<p>Per-product rate caps, all-in-cost APR, penal-interest cap, KFS cooling-off, consent lifecycle, DSR fulfillment, breach notification, and auto-purge are first-class features — not add-ons.</p>
</div>
<div class="uw-feature" markdown>
<h3>Provable event history</h3>
<p>Every event carries an Ed25519 signature. The 5-minute replay window and PII-redacted audit give you a defensible event ledger out of the box.</p>
</div>
<div class="uw-feature" markdown>
<h3>Pluggable backends</h3>
<p>Sqlite store (file or <code>:memory:</code>), local in-process bus, console or OTLP tracing, env / Vault / AWS secrets. Replace what you need to.</p>
</div>
<div class="uw-feature" markdown>
<h3>Small, opinionated primitives</h3>
<p>One <code>Core</code> base class, one <code>handle(event)</code> method, four-line event publish. You write the domain; the runtime wires the rest.</p>
</div>
<div class="uw-feature" markdown>
<h3>Tinker-friendly</h3>
<p>The whole runtime runs in a Python process with no broker, no cluster, no database server. Start with <code>Runtime()</code> and ship a demo in a day.</p>
</div>
<div class="uw-feature" markdown>
<h3>Operator-ready</h3>
<p>Health, readiness, Prometheus metrics, OpenTelemetry tracing, DLQ replay, sagas with compensating rollback, and a documented release process.</p>
</div>
</div>

## Quickstart

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate

underwrite init
underwrite run mechanism audit pricing compliance
```

In a second terminal, drive an end-to-end Indian lending lifecycle:

```bash
python docs/examples/indian_lending.py
```

The script seeds bank capital, onboards a borrower with PAN + Aadhaar, records DPDPA consent, runs KYC/AML, pulls CIBIL/CKYC, computes pricing under RBI caps, generates a KFS, and originates the loan — all against an in-memory store and bus. The full walkthrough is in [Quickstart](QUICKSTART/).

## What to read next

<div class="uw-features" markdown>
<div class="uw-feature" markdown>
<h3><a href="getting-started/">Getting started →</a></h3>
<p>The shortest path from <code>pip install</code> to a running service.</p>
</div>
<div class="uw-feature" markdown>
<h3><a href="TUTORIAL_FIRST_SERVICE/">Build your first service →</a></h3>
<p>Write a <code>Greeter</code> nano-service in under 50 lines and watch it dispatch an event end-to-end.</p>
</div>
<div class="uw-feature" markdown>
<h3><a href="architecture/">Architecture →</a></h3>
<p>How the event bus, store, authz, identity, sagas, and supervisor fit together — with diagrams.</p>
</div>
<div class="uw-feature" markdown>
<h3><a href="reference/">API reference →</a></h3>
<p>Every public symbol in <code>underwrite.*</code> with parameters, return types, and a runnable example.</p>
</div>
<div class="uw-feature" markdown>
<h3><a href="DEVELOPMENT/">Development guide →</a></h3>
<p>Set up a dev loop, run the test suite, ship a change.</p>
</div>
<div class="uw-feature" markdown>
<h3><a href="CONTRIBUTING/">Contributing →</a></h3>
<p>Branching strategy, code style, review expectations, and the ADR process.</p>
</div>
</div>

## Project status

Underwrite is on the v0.9 release line. v0.9 ships real KYC wire-protocol clients (PAN, Aadhaar eKYC, CIBIL, CKYC), a production Docker image, and the full CI gate suite. The v1.0 backlog — live partner-sandbox validation, e-NACH / UPI Autopay mandate collection, full RBAC, pre-built multi-arch images, on-call runbook — is tracked in [ROADMAP](ROADMAP/).

A Helm chart is **not** planned. Deploy the multi-arch container directly or with a project-specific compose / kustomize overlay.