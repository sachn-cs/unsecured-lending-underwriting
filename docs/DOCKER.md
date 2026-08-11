# Docker Image

The underwrite runtime ships as a multi-stage Docker image.
The image is non-root, has a healthcheck, and is published to
GitHub Container Registry on tagged releases.

## Build

The `Dockerfile` is the source of truth. Build locally with:

```bash
./scripts/build-image.sh           # underwrite:dev
./scripts/build-image.sh v0.9.0    # underwrite:v0.9.0
./scripts/build-image.sh v0.9.0 --push  # tag and push
```

Build args:

| Arg | Default | Description |
|-----|---------|-------------|
| `PYTHON_VERSION` | `3.12` | Python base image |
| `EXTRAS` | `serve,otlp,vault` | pip extras to install |
| `BUILD_VERSION` | `0.1.0` | OCI image version label |
| `GIT_COMMIT` | `dev` | OCI image revision label |
| `BUILD_DATE` | `unknown` | OCI image created label |

The build:

1. Compiles the wheel in a `builder` stage with
   `cryptography` and `pydantic` precompiled wheels.
2. Installs the wheel + the production extras in a clean layer.
3. Strips debug info from the `.so` files to shrink the image
   by ~30 MB.
4. Copies the installed packages and the `underwrite` CLI
   entrypoint to a clean `python:3.12-slim` runtime.
5. Creates a non-root `underwrite` user (UID 1001) and gives
   it ownership of `/data`.
6. Adds a `HEALTHCHECK` that pings `/healthz` every 30s with a
   5s timeout.
7. Sets the OCI labels (`org.opencontainers.image.*`) for
   registry compatibility.

## Run

The image's default command is `underwrite serve`:

```bash
docker run --rm -p 8080:8080 underwrite:dev
curl http://127.0.0.1:8080/healthz
```

For a full configuration:

```bash
docker run --rm \
    -p 8080:8080 \
    -v $PWD/underwrite.json:/app/underwrite.json:ro \
    -v $PWD/data:/data \
    -e UNDERWRITE_REQUIRE_AUTH=true \
    -e UNDERWRITE_API_TOKEN=$(cat /etc/underwrite/api-token) \
    underwrite:dev \
    --config /app/underwrite.json \
    serve --host 0.0.0.0 --port 8080
```

The CLI is also available — override the entrypoint:

```bash
docker run --rm --entrypoint underwrite underwrite:dev --help
docker run --rm --entrypoint underwrite underwrite:dev init /app/config.json
docker run --rm --entrypoint underwrite underwrite:dev run mechanism audit
```

## docker-compose

`docker-compose.yml` is the reference local-deployment
manifest: it brings up the runtime plus HashiCorp Vault 1.18 in
dev mode and an OpenTelemetry Collector. The runtime uses a
file-backed SQLite database mounted at `/data` and connects to
the in-network Vault via the service name; environment variables
on the `underwrite` service mirror the `UNDERWRITE_*` namespace
in the runtime config.

```bash
docker compose up -d
curl http://127.0.0.1:8000/healthz
```

Vault's dev root token defaults to `devroot`; override with
`VAULT_TOKEN=…` in the environment. The `underwrite_data`
named volume persists the file-store state across container
restarts.

## CI

`.github/workflows/docker.yml` builds the image on every push
to `master` and on every tag (`v*.*.*`). The job:

1. Sets up QEMU + Buildx
2. Builds the image with `--cache-from type=gha` so unchanged
   layers are pulled from the GitHub Actions cache
3. Smoke-tests the image by running `serve` in the background
   and curling `/healthz`
4. Smoke-tests the CLI by running `underwrite --help`
5. Pushes the image to `ghcr.io/${{ github.repository }}` on
   tag releases (no push on branch builds)

The smoke test uses `UNDERWRITE_REQUIRE_AUTH=false` so the
healthcheck endpoint is reachable without a token. Production
deployments set `UNDERWRITE_REQUIRE_AUTH=true` and the
`UNDERWRITE_API_TOKEN` env var; the image's `HEALTHCHECK` does
not require auth (it hits `/healthz`, not `/v1/publish`).

## Image size

| Variant | Size |
|---------|------|
| `underwrite:dev` (Python 3.12, runtime + production extras) | ~280 MB |
| `underwrite:dev` (multi-arch amd64 + arm64) | ~290 MB |
| `underwrite:dev` (distroless `python:3.12-distroless`) | ~210 MB (not yet wired) |

The distroless variant is on the v1.0 roadmap; the current
slim variant is the recommended target for v0.9 / v0.10.
