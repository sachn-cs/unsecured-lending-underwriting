# syntax=docker/dockerfile:1.7
# Multi-stage production Dockerfile for the underwrite runtime.
#
# Build:
#   docker build -t underwrite:local .
# Run:
#   docker run --rm -p 8080:8080 underwrite:local serve
# Run with full config:
#   docker run --rm -p 8080:8080 -v $PWD/underwrite.json:/app/underwrite.json \
#       underwrite:local --config /app/underwrite.json

ARG PYTHON_VERSION=3.12
ARG EXTRAS="serve,postgres,otlp,vault"

# =============================================================================
# Stage 1: builder — install build tooling, build the wheel.
# =============================================================================
FROM python:${PYTHON_VERSION}-slim AS builder

ARG PYTHON_VERSION
ARG EXTRAS

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SETUPTOOLS_SCM_PRETEND_VERSION=${BUILD_VERSION:-0.1.0}

WORKDIR /build

# Install build dependencies in a single layer. The cryptography
# wheel is precompiled for common Python versions, so this is fast.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential gcc && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY underwrite/ underwrite/

# Build the wheel and install it with the production extras. Use a
# clean install of just the wheel to keep the resulting layer small.
RUN pip install --upgrade pip build && \
    python -m build --wheel && \
    WHEEL=$(ls dist/*.whl | head -1) && \
    pip install "${WHEEL}[${EXTRAS}]" && \
    # The cryptography and pydantic wheels are heavy; drop the .so
    # debug info to shave ~30 MB off the resulting image.
    find /usr/local/lib/python3.*/site-packages -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true

# =============================================================================
# Stage 2: runtime — copy the installed wheel and the CLI entrypoint.
# =============================================================================
FROM python:${PYTHON_VERSION}-slim

ARG PYTHON_VERSION
ARG EXTRAS
ARG BUILD_VERSION=0.1.0
ARG GIT_COMMIT=dev
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="underwrite" \
      org.opencontainers.image.description="Indian retail lending platform with Ed25519-signed events, RBI-aligned pricing, DPDPA-compliant KYC" \
      org.opencontainers.image.source="https://github.com/sachncs/underwrite" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UNDERWRITE_DATA_DIR=/data

# Create the non-root user. The numeric UID/GID match the volumes
# in docker-compose.yml so the data volume can be chowned at
# deploy time without a copy on first write.
RUN groupadd --system --gid 1001 underwrite && \
    useradd --system --uid 1001 --gid 1001 --no-create-home --shell /sbin/nologin underwrite && \
    mkdir -p /data && chown underwrite:underwrite /data && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed Python packages and the CLI entrypoint from
# the builder. Use --chown to avoid a separate chown layer. The
# globs survive PYTHON_VERSION build-arg changes between 3.10 and 3.13.
COPY --from=builder --chown=underwrite:underwrite /usr/local/lib/python*/site-packages /usr/local/lib/python*/site-packages
COPY --from=builder --chown=underwrite:underwrite /usr/local/bin/underwrite /usr/local/bin/underwrite

# A healthcheck that pings the FastAPI liveness endpoint. The
# underwrite process binds 0.0.0.0:8080 by default.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://127.0.0.1:8080/healthz || exit 1

EXPOSE 8080

USER underwrite

# Default command runs the FastAPI daemon. Override with
# `underwrite init` / `underwrite run <services>` for one-off use.
ENTRYPOINT ["underwrite"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
