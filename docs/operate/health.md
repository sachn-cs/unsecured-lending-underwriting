# Health and readiness

The runtime exposes three probes that map cleanly to Kubernetes'
liveness, readiness, and full-health concepts. Each probe is a
distinct HTTP endpoint with a distinct response shape — you wire
them to your platform's platform primitives without translation.

## The probes

| Endpoint | Verb | Purpose | Returns 200 when |
|----------|------|---------|------------------|
| `/healthz` | GET | Liveness | The process is alive |
| `/readyz` | GET | Readiness | The store is reachable and the runtime is initialized |
| `/v1/health` | GET | Full health | All subsystems respond (bus, store, authz, metrics, tracer, saga, supervisor) |

### `/healthz` — liveness

The cheapest possible check. The runtime responds `200 OK` with
a tiny JSON body as long as the FastAPI daemon can serve requests.

```bash
$ curl -i http://localhost:8080/healthz
HTTP/1.1 200 OK
content-type: application/json
content-length: 23

{"status":"alive"}
```

Wire `/healthz` to Kubernetes' `livenessProbe`. The kubelet will
restart the pod only when this probe times out for `failureThreshold`
consecutive checks.

### `/readyz` — readiness

A deeper check: the runtime responds `200 OK` only when the store
is reachable and the runtime has completed initialization. While
migrations are running or the runtime is starting up, `/readyz`
returns `503 Service Unavailable`.

```bash
$ curl -i http://localhost:8080/readyz
HTTP/1.1 200 OK
content-type: application/json

{"ready": true, "store": {"ok": true}}
```

Wire `/readyz` to Kubernetes' `readinessProbe`. The kubelet will
stop routing traffic to the pod only when this probe fails — for
example, during a database outage.

### `/v1/health` — full subsystem report

The complete view. Every subsystem is reported with its
`HealthCheck` result:

```bash
$ curl http://localhost:8080/v1/health | python -m json.tool
{
  "bus": {"ok": true, "buffered": 0},
  "store": {"ok": true, "path": "./store.db"},
  "authz": {"ok": true, "policies": 5, "trusted_keys": 4},
  "metrics": {"ok": true, "counters": 123, "timers": 56, "gauges": 8},
  "tracer": {"ok": true, "spans": 1024},
  "saga": {"ok": true, "active": 2},
  "supervisor": {"ok": true, "restarts": 0}
}
```

Use `/v1/health` from your monitoring system to alert on any
subsystem going unhealthy.

## Subsystem checks

Each subsystem implements a `HealthCheck` — a callable that
returns `{"{"ok": True/False, ...detail"}"}`. The runtime registers
each subsystem at construction time.

| Subsystem | Health detail |
|-----------|---------------|
| Bus | buffered events, breaker state |
| Store | path, file size, last sync |
| Authz | policy count, trusted key count |
| Metrics | counter / timer / gauge counts |
| Tracer | span count, exporter state |
| Saga | active saga count |
| Supervisor | restart count, current backoff |

You can read the in-process view directly:

```python
runtime.health.status()
```

## Kubernetes example

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /readyz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 2
```

## Failure modes

| Symptom | Likely cause | Recovery |
|---------|--------------|----------|
| `/healthz` returns 200 but `/readyz` returns 503 | Store is unreachable; migrations running | Wait for migrations; restart the pod if the store is dead |
| `/v1/health` shows `authz.ok: false` | Policy file is missing or malformed | Check the policy file path; restart after fixing |
| `/v1/health` shows `metrics.ok: false` | Metrics collector over the cap and evictions are failing | Increase `max_metrics` or reduce cardinality |
| `/v1/health` shows `supervisor.restarts > 0` | A service crashed and the supervisor is restarting it | Inspect the audit log and DLQ; the restart is automatic |

## See also

- [Observability](observability.md) — metrics and traces that complement the probes.
- [Operations](operations.md) — incident response playbook.
- [Deployment](deployment.md) — wiring the runtime into Kubernetes.