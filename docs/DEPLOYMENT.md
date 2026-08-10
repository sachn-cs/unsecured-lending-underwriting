# Deployment Guide

## Docker Deployment

The `Dockerfile` uses a multi-stage build with a `python:3.12-slim` runtime image. The container runs as an unprivileged `underwrite` user (UID 1001).

```dockerfile
# Stage 1: builder — install build deps, compile wheel
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml README.md ./
COPY underwrite/ underwrite/
RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir cryptography pydantic typer && \
    python -m build --wheel && \
    pip install --no-cache-dir dist/*.whl[serve,postgres,otlp]

# Stage 2: runtime — minimal image
FROM python:3.12-slim
RUN addgroup --system --gid 1001 underwrite && \
    adduser --system --uid 1001 --ingroup underwrite underwrite
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/underwrite /usr/local/bin/underwrite
RUN mkdir -p /data && chown underwrite:underwrite /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1
USER underwrite
ENTRYPOINT ["underwrite"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
```

### Build and Run

```bash
docker build -t underwrite:latest .
docker run -d \
  --name underwrite \
  -p 8000:8080 \
  -e UNDERWRITE_API_TOKEN=prod-token \
  -e UNDERWRITE_STORE_BACKEND=filesystem \
  -e UNDERWRITE_LOG_FORMAT=json \
  underwrite:latest
```

Verify:

```bash
curl -sf http://localhost:8000/healthz | python -m json.tool
```

---

## India Cloud Deployment

### AWS (ap-south-1 — Mumbai)

```yaml
# Kubernetes nodeSelector for Indian data residency
nodeSelector:
  topology.kubernetes.io/region: ap-south-1

# RDS PostgreSQL in Mumbai region
store:
  backend: postgres
  dsn: postgresql://user:pass@underwrite.cluster-xxx.ap-south-1.rds.amazonaws.com:5432/underwrite
```

### Azure (Central India)

```yaml
nodeSelector:
  topology.kubernetes.io/region: centralindia

# Azure Database for PostgreSQL
store:
  backend: postgres
  dsn: postgresql://user:pass@underwrite.postgres.database.azure.com:5432/underwrite
```

### GCP (asia-south1 — Mumbai)

```yaml
nodeSelector:
  topology.kubernetes.io/region: asia-south1

# Cloud SQL PostgreSQL
store:
  backend: postgres
  dsn: postgresql://user:pass@10.x.x.x:5432/underwrite
```

### Data Localisation Requirements

All deployment targets must ensure:
- **Compute and storage** in the same Indian region (no cross-border data transfer)
- **Secrets backend** (Vault/AWS SM) also in-region
- **Event bus** (SQS/Modal) regional endpoint
- **Monitoring** (OTLP collector, metrics) in-region

For MeitY-empanelled cloud providers, refer to the [MeitY Cloud Framework](https://www.meity.gov.in/cloud-framework).

---

## Docker Compose

`docker-compose.yml` configures a production-grade deployment with PostgreSQL 16, HashiCorp Vault, and OpenTelemetry Collector:

```yaml
services:
  underwrite:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8080"
    environment:
      - UNDERWRITE_STORE_BACKEND=postgres
      - UNDERWRITE_STORE_DSN=postgresql://underwrite:${POSTGRES_PASSWORD}@postgres:5432/underwrite
      - UNDERWRITE_SECRETS_BACKEND=vault
      - UNDERWRITE_SECRETS_VAULT_URL=http://vault:8200
      - UNDERWRITE_TRACING_ENABLED=true
      - UNDERWRITE_TRACING_EXPORTER=otlp
      - UNDERWRITE_API_TOKEN=${UNDERWRITE_API_TOKEN:-}
    depends_on:
      postgres:
        condition: service_healthy
      vault:
        condition: service_healthy
    command: ["serve", "--services", "mechanism,audit,risk,fraud,compliance,pricing,consent,kfs,credit_bureau,underwriter,decision", "--rate-limit", "100"]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: underwrite
      POSTGRES_USER: underwrite
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U underwrite"]

  vault:
    image: hashicorp/vault:latest
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: ${VAULT_TOKEN}
      VAULT_DEV_LISTEN_ADDRESS: 0.0.0.0:8200
    cap_add:
      - IPC_LOCK
    healthcheck:
      test: ["CMD", "vault", "status"]

  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: ["--config=/etc/otel-collector.yml"]
    volumes:
      - ./otel-collector.yml:/etc/otel-collector.yml
    ports:
      - "4317:4317"  # OTLP gRPC
      - "4318:4318"  # OTLP HTTP
```

Start:

```bash
POSTGRES_PASSWORD=changeme VAULT_TOKEN=dev-token UNDERWRITE_API_TOKEN=prod-token docker compose up -d
```

---

## Kubernetes

### Probes

```yaml
containers:
  - name: underwrite
    image: underwrite:latest
    ports:
      - containerPort: 8080
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 15
      periodSeconds: 30
    readinessProbe:
      httpGet:
        path: /readyz
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
```

### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: underwrite-config
data:
  underwrite.json: |
    {
      "store": { "backend": "postgres", "dsn": "postgresql://..." },
      "logging": { "level": "INFO", "log_format": "json" },
      "metrics": { "enabled": true },
      "authz": { "enabled": true },
      "migration": { "auto_migrate": true },
      "saga": { "enabled": true },
      "recovery": { "auto_restart": true }
    }
```

Mount the ConfigMap at `/app/underwrite.json`.

### Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: underwrite-secrets
type: Opaque
stringData:
  UNDERWRITE_API_TOKEN: <production-token>
  UNDERWRITE_STORE_DSN: postgresql://user:pass@host:5432/underwrite
```

```yaml
envFrom:
  - secretRef:
      name: underwrite-secrets
```

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: underwrite
spec:
  replicas: 2
  selector:
    matchLabels:
      app: underwrite
  template:
    metadata:
      labels:
        app: underwrite
    spec:
      containers:
        - name: underwrite
          image: underwrite:latest
          ports:
            - containerPort: 8080
          env:
            - name: UNDERWRITE_STORE_BACKEND
              value: postgres
            - name: UNDERWRITE_LOG_FORMAT
              value: json
          envFrom:
            - secretRef:
                name: underwrite-secrets
          volumeMounts:
            - name: config
              mountPath: /app/underwrite.json
              subPath: underwrite.json
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
      volumes:
        - name: config
          configMap:
            name: underwrite-config
```

---

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on push/PR to `main`:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e '.[dev,risk,serve,postgres,otlp,vault,aws]'
      - run: ruff check underwrite/ tests/        # lint
      - run: mypy underwrite/                      # type check
      - run: bandit -r underwrite/ -c pyproject.toml  # security audit
      - run: pip-audit                             # dependency audit
      - run: python -m pytest tests/ -v            # test suite

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t underwrite:ci .
      - run: |
          docker run -d --name underwrite-ci -p 8080:8080 underwrite:ci
          sleep 5
          curl -sf http://localhost:8080/healthz || exit 1
          docker stop underwrite-ci
```

The pipeline matrix lints with `ruff`, type-checks with `mypy`, audits with `bandit` and `pip-audit`, runs the full test suite, builds the Docker image, and smoke-tests the container with a health check.

---

## Configuration Management

### Configuration File

`underwrite.json` is loaded from the working directory at startup. Environment-specific files are supported via `UNDERWRITE_ENV`:

```json
{
  "store": {
    "backend": "postgres",
    "dsn": "postgresql://user:pass@host:5432/underwrite"
  },
  "logging": {
    "level": "INFO",
    "log_format": "json"
  },
  "services": {
    "mechanism": { "enabled": true },
    "audit": { "enabled": true },
    "risk": { "enabled": true },
    "fraud": { "enabled": true }
  }
}
```

### Env Var Overrides

Every config key can be overridden via `UNDERWRITE_*` environment variables:

| Env Var | Config Path | Type |
|---------|-------------|------|
| `UNDERWRITE_STORE_BACKEND` | `store.backend` | string |
| `UNDERWRITE_STORE_DSN` | `store.dsn` | string |
| `UNDERWRITE_LOG_LEVEL` | `logging.level` | string |
| `UNDERWRITE_LOG_FORMAT` | `logging.log_format` | string |
| `UNDERWRITE_DATA_DIR` | `data_dir` | string |
| `UNDERWRITE_AUTHZ_ENABLED` | `authz.enabled` | bool |
| `UNDERWRITE_METRICS_ENABLED` | `metrics.enabled` | bool |
| `UNDERWRITE_TRACING_ENABLED` | `tracing.enabled` | bool |
| `UNDERWRITE_TRACING_EXPORTER` | `tracing.exporter` | string (console/otlp/noop) |
| `UNDERWRITE_SAGA_ENABLED` | `saga.enabled` | bool |
| `UNDERWRITE_RECOVERY_AUTO_RESTART` | `recovery.auto_restart` | bool |
| `UNDERWRITE_RECOVERY_MAX_RESTARTS` | `recovery.max_restarts` | int |
| `UNDERWRITE_SECRETS_BACKEND` | `secrets.backend` | string |
| `UNDERWRITE_SECRETS_VAULT_URL` | `secrets.url` | string |
| `UNDERWRITE_SECRETS_VAULT_TOKEN` | `secrets.token` | string |
| `UNDERWRITE_SECRETS_AWS_REGION` | `secrets.region` | string |
| `UNDERWRITE_BUS_RATE_LIMIT` | `bus.rate_limit` | float |
| `UNDERWRITE_BUS_MAX_WORKERS` | `bus.max_workers` | int |

For secrets, use `UNDERWRITE_API_TOKEN` in the environment (not in config files) to prevent exposure.

---

## Production Checklist

- [ ] **Set `UNDERWRITE_API_TOKEN`** — authentication for HTTP endpoints
- [ ] **Configure store backend** — `postgres` for production, set `UNDERWRITE_STORE_DSN`
- [ ] **Enable authz** — `authz.enabled: true` with a policy file
- [ ] **Configure observability**
  - Set `UNDERWRITE_LOG_FORMAT=json` for structured logging
  - Configure OpenTelemetry: `tracing.enabled: true`, `tracing.exporter: otlp`
  - Enable metrics: `metrics.enabled: true`
- [ ] **Set data directory** — `UNDERWRITE_DATA_DIR=/data` with persistent volume
- [ ] **Enable migrations** — `migration.auto_migrate: true` (default)
- [ ] **Configure recovery** — enable supervisor auto-restart
- [ ] **Set resource limits** — CPU/memory limits in Kubernetes
- [ ] **Health check endpoints** — configure `/healthz` and `/readyz` probes
- [ ] **Set environment** — `UNDERWRITE_ENV=production` loads `config.production.json`

---

## Health Check Endpoints

| Endpoint | Path | Use |
|----------|------|-----|
| Liveness | `GET /healthz` | Kubernetes liveness probe |
| Readiness | `GET /readyz` | Kubernetes readiness probe |
| Full health | `GET /v1/health` | Detailed subsystem health |
| Legacy | `GET /health` | Backward-compatible health |

All health endpoints return the same JSON body:

```json
{
  "status": "healthy",
  "ok": true,
  "checks": {
    "bus": { "ok": true, "subscribers": 4, "dlq_count": 0 },
    "store": { "ok": true },
    "services": { "ok": true, "running": ["mechanism", "audit"] }
  },
  "checked_at": "2026-06-08T12:00:00+00:00"
}
```

---

## Store Backends

| Backend | Config Value | Use Case |
|---------|-------------|----------|
| Filesystem | `filesystem` | Single-node, dev/staging (JSON files in `data/`) |
| In-memory | `memory` | Testing, ephemeral workloads |
| PostgreSQL | `postgres` | Production multi-node (requires `underwrite[postgres]`) |

### CQRS

Configure a separate read store for query side:

```json
{
  "store": {
    "backend": "postgres",
    "read_backend": "postgres",
    "read_dsn": "postgresql://readonly:pass@replica:5432/underwrite"
  }
}
```

---

## Service Registration

The Runtime discovers services via `SERVICE_MAP` in `handler.py`. Available services:

| Service | Description |
|---------|-------------|
| `mechanism` | Core protocol — seeds, budgets, delegation |
| `audit` | Event ledger with PII redaction |
| `risk` | Risk scoring (requires `numpy`/`scikit-learn`) |
| `fraud` | Fraud detection (velocity, wash trading) |
| `quote` | Quote generation |
| `pricing` | Pricing computation |
| `decision` | Loan decision evaluation |
| `underwriter` | Underwriting approval workflow |
| `origination` | Loan origination |
| `servicing` | Loan servicing |
| `payment` | Payment processing |
| `fee` | Fee assessment |
| `collection` | Collections management |
| `npa` | Non-performing asset tracking |
| `collateral` | Collateral management |
| `recovery` | Post-default recovery |
| `compliance` | Compliance checks (KYC/AML) |
| `identity` | Identity management |
| `notification` | Notification dispatch |
| `document` | Document generation |
| `disbursement` | Loan disbursement |
| `settlement` | Settlement processing |
| `statement` | Statement generation |
| `reporting` | Reporting |
| `communication` | Communication dispatch |
| `workflow` | Workflow orchestration |
| `governance` | Protocol governance |
| `graph` | Graph queries for credit limits |

Start subsets with: `underwrite serve --services "mechanism,audit,risk,fraud"`
