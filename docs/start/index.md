# Start

The shortest path from a clean checkout to a running Underwrite
runtime with your first event flowing through the bus.

This section is the entry point for new users. The pages below are
ordered from "clone and run" to "wire up a real scenario".

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<h3>Install</h3>
<p>System requirements, the <code>setup.sh</code> bootstrap script, the available extras (<code>[risk]</code>, <code>[serve]</code>, <code>[otlp]</code>, <code>[vault]</code>, <code>[aws]</code>, <code>[gcs]</code>, <code>[modal]</code>), and Docker / docker-compose paths.</p>
<a href="install/">Install →</a>
</div>

<div class="uw-card" markdown>
<h3>Quickstart</h3>
<p>The annotated <code>indian_lending.py</code> walkthrough: bank seeds capital, borrower onboards with PAN + Aadhaar, DPDPA consent recorded, KYC/AML clears, CIBIL pulled, pricing computed under RBI caps, KFS issued, loan originated.</p>
<a href="quickstart/">Quickstart →</a>
</div>

<div class="uw-card" markdown>
<h3>First service</h3>
<p>Write a 50-line Greeter nano-service that listens for one event type and emits another. See the runtime guarantees arrive by construction.</p>
<a href="first-service/">First service →</a>
</div>

<div class="uw-card" markdown>
<h3>Event bus</h3>
<p>What happens between <code>runtime.publish</code> and the receiving service's <code>handle(event)</code>. Authz, signing, idempotency, tracing, metrics, DLQ, circuit breaking.</p>
<a href="event-bus/">Event bus →</a>
</div>

<div class="uw-card" markdown>
<h3>Custom nano-services</h3>
<p>Stateless and stateful reducer patterns. The patterns used by the 34 wired services, distilled.</p>
<a href="custom-nano/">Custom nano-services →</a>
</div>

<div class="uw-card" markdown>
<h3>Pluggable backends</h3>
<p>Swap the store, bus, secrets manager, tracer, or metrics exporter for your own implementation. The runtime only depends on the public protocol.</p>
<a href="plugins/">Pluggable backends →</a>
</div>

<div class="uw-card" markdown>
<h3>Indian lending example</h3>
<p>The full <code>indian_lending.py</code> script with line-by-line context. Read alongside the quickstart page.</p>
<a href="examples/indian_lending.py">View source →</a>
</div>

<div class="uw-card" markdown>
<h3>Need a different path?</h3>
<p>Architects and risk reviewers can skip to <a href="../understand/architecture/">architecture</a>, <a href="../understand/compliance/">compliance</a>, or <a href="../understand/security/">security</a>.</p>
</div>
</div>