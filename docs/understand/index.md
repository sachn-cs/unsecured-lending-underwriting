# Understand

This section is for readers who want to know **how** Underwrite
works before they write code. Architecture, lifecycle, runtime
guarantees, compliance, and security.

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<h3>Architecture</h3>
<p>The full architecture overview — domain services, event runtime, control plane, operational layer, and the injection points where cross-cutting concerns enter the dispatch path.</p>
<a href="architecture/">Architecture →</a>
</div>

<div class="uw-card" markdown>
<h3>Indian lending lifecycle</h3>
<p>The full underwriting journey in twelve stages, with the service, event, and compliance responsibility at each transition.</p>
<a href="lifecycle/">Lifecycle →</a>
</div>

<div class="uw-card" markdown>
<h3>Compliance</h3>
<p>How RBI rate caps, all-in-cost APR, KFS cooling-off, DPDPA consent lifecycle, and DSR fulfillment are encoded as runtime defaults — not application-level conventions.</p>
<a href="compliance/">Compliance →</a>
</div>

<div class="uw-card" markdown>
<h3>Security</h3>
<p>Ed25519 signatures, replay window, PII-redacted audit, deterministic event records — the security posture of the runtime.</p>
<a href="security/">Security →</a>
</div>

<div class="uw-card" markdown>
<h3>Runtime</h3>
<p>The <code>underwrite.runtime.Runtime</code> orchestrator — service registration, dependency injection, identity creation, authz wiring, and lifecycle.</p>
<a href="runtime/">Runtime →</a>
</div>

<div class="uw-card" markdown>
<h3>Events</h3>
<p>The <code>Message</code> envelope, the canonical signing bytes, the <code>Type</code> enum of 132 event types, and the event lifecycle from create to replay.</p>
<a href="events/">Events →</a>
</div>

<div class="uw-card" markdown>
<h3>Failure handling</h3>
<p>DLQ, idempotency, sagas with compensating rollback, circuit breaking, supervisor auto-restart, and the rules of thumb for each.</p>
<a href="failure-handling/">Failure handling →</a>
</div>

<div class="uw-card" markdown>
<h3>System design</h3>
<p>End-to-end runtime behavior — bus dispatch, store writes, saga execution, traced and instrumented.</p>
<a href="system-design/">System design →</a>
</div>

<div class="uw-card" markdown>
<h3>Directory structure</h3>
<p>The full <code>underwrite/</code> package layout — every module's purpose and what it depends on.</p>
<a href="directory-structure/">Directory structure →</a>
</div>

<div class="uw-card" markdown>
<h3>Design decisions</h3>
<p>The ADRs and design notes behind nano-service isolation, typed events, Ed25519 signatures, and saga orchestration.</p>
<a href="design-decisions/">Design decisions →</a>
</div>

<div class="uw-card" markdown>
<h3>Domain model</h3>
<p>Core entities — borrower, loan, mandate, KYC, KFS — and the invariants the runtime enforces.</p>
<a href="domain-model/">Domain model →</a>
</div>
</div>