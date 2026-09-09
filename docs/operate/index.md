# Operate

Pages for the people running Underwrite in production — SREs,
operators, on-call engineers.

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<h3>Deployment</h3>
<p>Multi-stage Docker image, multi-arch builds, container hardening, and the production environment variables.</p>
<a href="deployment/">Deployment →</a>
</div>

<div class="uw-card" markdown>
<h3>Operations</h3>
<p>Day-2 operations — restarts, log capture, configuration reloads, key rotation, and incident triage.</p>
<a href="operations/">Operations →</a>
</div>

<div class="uw-card" markdown">
<h3>Observability</h3>
<p>Prometheus metrics on <code>/metrics</code>, OpenTelemetry tracing (console / OTLP), structured log output, and what to alert on.</p>
<a href="observability/">Observability →</a>
</div>

<div class="uw-card" markdown>
<h3>Health and readiness</h3>
<p><code>/healthz</code>, <code>/readyz</code>, and <code>/v1/health</code> — what each probe checks and how to wire them into Kubernetes.</p>
<a href="health/">Health →</a>
</div>

<div class="uw-card" markdown>
<h3>DLQ and replay</h3>
<p>Inspecting the dead-letter queue, replaying events, and the rules of thumb for poisoning recovery.</p>
<a href="dlq/">DLQ →</a>
</div>

<div class="uw-card" markdown>
<h3>Performance</h3>
<p>Throughput baselines, latency budgets, and the knobs that move each.</p>
<a href="performance/">Performance →</a>
</div>

<div class="uw-card" markdown>
<h3>Database</h3>
<p>The SQLite store, WAL journaling, busy timeout, schema migrations, and durable DLQ.</p>
<a href="database/">Database →</a>
</div>

<div class="uw-card" markdown>
<h3>Migrations</h3>
<p>Transactional schema migrations and how to write one.</p>
<a href="migrations/">Migrations →</a>
</div>

<div class="uw-card" markdown>
<h3>Debugging</h3>
<p>Reading the audit ledger, dumping traces, and the most common runtime traps.</p>
<a href="debugging/">Debugging →</a>
</div>

<div class="uw-card" markdown>
<h3>Release process</h3>
<p>Tag-driven publishing, reproducible wheels, GitHub Actions matrix, and the on-call checklist.</p>
<a href="release-process/">Release →</a>
</div>

<div class="uw-card" markdown>
<h3>Changelog guide</h3>
<p>Keep-a-Changelog format, release categorization, and how to move items from Unreleased to a tagged section.</p>
<a href="changelog-guide/">Changelog →</a>
</div>

<div class="uw-card" markdown">
<h3>Docker</h3>
<p>Building the multi-arch image, running it locally, and the docker-compose profiles.</p>
<a href="docker/">Docker →</a>
</div>
</div>