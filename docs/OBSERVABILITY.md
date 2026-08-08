# Observability

The underwrite platform provides integrated logging, metrics, tracing, and
health checks.  Every nano service inherits observability from
`NanoService` — no per-service instrumentation boilerplate.

---

## Logging

**Module:** `underwrite/__logger__.py`

A single module-level `logger` imported from `underwrite.__logger__` is
used throughout.  Configuration is managed by `Runtime.__configure_logging()`
in `underwrite/__runtime__.py`.

### Levels

`DEBUG`, `INFO`, `WARNING`, `ERROR` — set via `UNDERWRITE_LOG_LEVEL` env
var (default: `INFO`).

### Format

- **JSON** (default when `UNDERWRITE_LOG_FORMAT=json`):
  ```json
  {"timestamp": "...", "level": "INFO", "logger": "underwrite",
   "message": "...", "module": "foo", "line": 42,
   "correlation_id": "uuid", "trace_id": "uuid",
   "exception": "Traceback ..."}
  ```
  `correlation_id` is present when a correlation id is set on the
  current thread; `trace_id` is present when bound via
  `logger.bind(trace_id=...)`; `exception` is present when the record
  carries a traceback.  The `JsonFormatter` recursively redacts sensitive keys
  (`password`, `secret`, `token`, `ssn`, `pan`, `account`, `pin`,
  `cvv`, etc.) using **token-based** matching: each key is split on
  non-alphanumeric boundaries and each token is tested for set
  membership. The previous substring-after-lowercasing behaviour
  over-matched innocent field names like `company` against `pan`;
  the token-based form does not.

- **Text** (default otherwise):
  ```
  2025-01-15 10:00:00 [INFO] <correlation_id> underwrite: message
  ```

### Correlation ID

Attached per-thread via `correlation_context` in
`underwrite/__correlation__.py`.  The formatters read it through
`correlation_id()` in `underwrite/__logger__.py`.  `NanoService.__handle_event()`
sets the correlation id from `event.correlation_id` before calling
`handle()` and restores the previous value afterwards.

### Configuration

| Env var | Default | Description |
|---|---|---|
| `UNDERWRITE_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `UNDERWRITE_LOG_FORMAT` | `text` | `json` or `text` |

---

## Metrics

**Modules:** `underwrite/__metrics__.py`, `underwrite/prometheus_export.py`

### Collector

`MetricsCollector` is a thread-safe in-memory store for:

- **Counter** — monotonically increasing integers
- **Gauge** — point-in-time float values
- **Timer** — duration statistics (count, total_ms, min_ms, max_ms)

```python
metrics = MetricsCollector(max_metrics=10000)
metrics.increment("events.handled", {"service": "audit", "event_type": "loan.originated"})
metrics.gauge("queue.depth", 42)
with metrics.time("handle.duration", {"service": "audit"}):
    process(event)
```

`max_metrics=10000` bounds total metric entries.  When exceeded, the
oldest entries across all metric types are evicted (O(1) per eviction).

### Auto-collected Metrics

`NanoService.__handle_event()` and `emit()` in `services/base.py`
automatically record:

| Metric | Type | Tags |
|---|---|---|
| `events.emitted` | Counter | `service`, `event_type` |
| `events.handled` | Counter | `service`, `event_type` |
| `events.failed` | Counter | `service`, `event_type` |
| `handle.duration` | Timer | `service`, `event_type` |

### Prometheus Export

`MetricsExporter.to_prometheus_text()` serialises the collector snapshot
into the Prometheus exposition format (`text/plain; version=0.0.4`).

**Endpoint:** `/v1/metrics` (via `__serve__.py`)

**Middleware:** `PrometheusMiddleware` adds `/metrics-prometheus` to any
Starlette/FastAPI application. When `UNDERWRITE_API_TOKEN` (or the
`api_token` constructor argument) is set, the endpoint requires
`Authorization: Bearer <token>` and returns 401 otherwise. When no
token is configured the endpoint is open (the metrics port is
expected to be on a private network). Tag values are escaped for
backslash, double-quote and newline so a user-controlled tag cannot
break out of the label string; tag values are also run through the
PII redactor so PAN/Aadhaar/mobile numbers cannot end up in the
Prometheus TSDB.

**Periodic export thread:** `Runtime.__start_metrics_export()` launches
a daemon thread that snapshots and logs metrics at a configurable
interval (only when OTLP exporter is configured).

### Configuration

| Config key | Default | Description |
|---|---|---|
| `metrics.enabled` | `true` | Enable the metrics collector |
| `metrics.export_interval` | `0` | Seconds between periodic exports (0 = off) |

---

## Tracing

**Module:** `underwrite/__tracer__.py`

### Spans

Every span carries: `trace_id`, `span_id`, `parent_span_id`,
`service_id`, `operation`, `start_ms`, `end_ms`, `tags`, `error`.

### Tracer

Created in `Runtime.__build_tracer()`:

```python
Tracer(service_id="runtime", exporter=ConsoleSpanExporter())
```

- **ConsoleSpanExporter** — logs span details via `logger.info()` for
  local development.
- **OtlpSpanExporter** — lazy-init OpenTelemetry SDK and exports via
  OTLP/gRPC (`localhost:4317`).  Requires the `otlp` extra:
  ```
  pip install underwrite[otlp]
  ```
- Default: `SpanExporter` (no-op).

### Auto-tracing

`NanoService.__handle_event()` wraps every `self.handle()` call in a
trace span:

```python
with self.__tracer.trace(f"handle.{event.event_type}",
                          trace_id=..., parent_span_id=..., tags=...):
    self.handle(event)
```

Trace context (`trace_id`, `parent_span_id`) propagates through the
`Event` envelope — emitted events carry the current trace IDs, forming
a distributed trace across services.

### Span Bounds

`max_spans=10000` prevents unbounded memory growth.  Overflow spans
are exported and dropped.

### Configuration

| Config key | Default | Description |
|---|---|---|
| `tracing.enabled` | `false` | Enable distributed tracing |
| `tracing.exporter` | `console` | `console` or `otlp` |

---

## Health Checks

**Modules:** `underwrite/__health__.py`, `underwrite/__runtime__.py`

### HealthRegistry

Thread-safe registry of named `Callable[[], dict]` checks.  Each check
returns `{"ok": bool, ...}`.  `status()` aggregates into:

```json
{"status": "healthy", "ok": true, "checks": {...}, "checked_at": "..."}
```

### Registered Checks

Registered in `Runtime.__register_subsystem_health()`:

| Check | What it verifies |
|---|---|
| `bus` | Bus not stopped, subscriber count, DLQ count |
| `store` | `Store.health()` — connectivity check |
| `read_store` | Read store connectivity (if configured) |
| `services` | List of running services |
| `metrics` | Metrics collector is alive |
| `tracer` | Tracer is alive, span count |
| `saga` | Saga orchestrator is alive |
| `dlq` | Dead-letter queue count |
| `supervisor` | Service supervisor health |
| `service:<id>` | Per-service health (running, events handled/failed) |

### HTTP Endpoints

| Endpoint | Type | Use |
|---|---|---|
| `/healthz` | Liveness | K8s liveness probe (200 = healthy, 503 = degraded) |
| `/readyz` | Readiness | K8s readiness probe |
| `/v1/health` | Full | Aggregated health with per-check detail |

### CLI

```
underwrite health
```

Creates a readonly `Runtime`, calls `health.status()`, and prints a
check-by-check report:

```
Status: healthy
OK: True
Checks:
  [OK] bus
  [OK] store
  [OK] services — running: mechanism, audit
```

---

## Data Flow Diagram

```mermaid
flowchart LR
    subgraph NanoService
        H[handle event]
        E[emit event]
    end

    subgraph Logging
        LC[correlation_context]
        JF[JsonFormatter<br/>PII redaction]
    end

    subgraph Metrics
        MC[MetricsCollector]
        MX[MetricsExporter]
        PT[Prometheus<br/>/v1/metrics]
    end

    subgraph Tracing
        TR[Tracer]
        CS[ConsoleSpanExporter]
        OT[OtlpSpanExporter<br/>OTLP/gRPC]
    end

    subgraph Health
        HR[HealthRegistry]
        HZ[/healthz]
        RZ[/readyz]
        VH[/v1/health]
    end

    H --> LC
    H --> TR
    H --> MC
    H --> HR

    E --> MC
    E --> TR

    LC --> JF --> stdout
    TR --> CS --> Logging
    TR --> OT --> OTLP

    MC --> MX --> PT
    HR --> HZ
    HR --> RZ
    HR --> VH

    Event((Event<br/>envelope)) -.->|trace_id<br/>parent_span_id<br/>correlation_id| TR
```
