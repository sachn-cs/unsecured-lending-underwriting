# Build

Pages for readers who want to write services, configure the runtime,
and integrate Underwrite into their own infrastructure.

<div class="grid grid-2" markdown>
<div class="uw-card" markdown>
<h3>Development guide</h3>
<p>Dev loop, test runner, lint / typecheck / security gates, and the conventions every service follows.</p>
<a href="index/">Development →</a>
</div>

<div class="uw-card" markdown>
<h3>Services</h3>
<p>The 34 wired nano-services and the events they emit and consume. How to wire a custom service into the bus.</p>
<a href="services/">Services →</a>
</div>

<div class="uw-card" markdown>
<h3>Configuration</h3>
<p>The full <code>Configuration</code> surface — 28 sections, ~120 keys. JSON file, env vars, and the merge order.</p>
<a href="configuration/">Configuration →</a>
</div>

<div class="uw-card" markdown>
<h3>Sagas</h3>
<p>Multi-step workflows, compensating actions, and the orchestrator's persistence semantics.</p>
<a href="sagas/">Sagas →</a>
</div>

<div class="uw-card" markdown>
<h3>KYC integrations</h3>
<p>PAN, Aadhaar eKYC, CIBIL, and CKYC wire-protocol clients. Sandbox URLs and partner credential handling.</p>
<a href="kyc-integrations/">KYC →</a>
</div>

<div class="uw-card" markdown>
<h3>Environment variables</h3>
<p>Every <code>UNDERWRITE_*</code> variable, its default, and the configuration section it overrides.</p>
<a href="environment-variables/">Env vars →</a>
</div>

<div class="uw-card" markdown>
<h3>Dependencies</h3>
<p>The extras taxonomy, optional installs, and upgrade considerations.</p>
<a href="dependencies/">Dependencies →</a>
</div>

<div class="uw-card" markdown>
<h3>Code style</h3>
<p>Google-style docstrings, type hints, line length, visibility, and the linters that enforce them.</p>
<a href="code-style/">Code style →</a>
</div>

<div class="uw-card" markdown>
<h3>Testing</h3>
<p>The pytest layout, coverage gate, and the conventions for service-level and integration tests.</p>
<a href="testing/">Testing →</a>
</div>

<div class="uw-card" markdown>
<h3>Build</h3>
<p>Packaging with <code>setuptools_scm</code> + <code>build</code>, reproducible wheels, and the multi-stage production Dockerfile.</p>
<a href="build/">Build →</a>
</div>
</div>