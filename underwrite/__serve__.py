"""HTTP server for the underwrite Runtime.

Provides health, metrics, and event-publishing endpoints with
optional bearer token authentication.

Endpoints are versioned under ``/v1/``.  Every response includes a
``X-Request-ID`` header for distributed tracing correlation.
"""

from __future__ import annotations

__all__ = [
    "create_app",
]

import hmac
import importlib.metadata
import os
import re
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from underwrite.__exceptions__ import ProtocolError
from underwrite.__logger__ import logger

__VALID_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
__VALID_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_.-]+$")


def __error_response(status_code: int, message: str, request_id: str = "") -> JSONResponse:
    """Build a structured error envelope."""
    body: dict[str, Any] = {
        "error": message,
        "status_code": status_code,
    }
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=body)


def try_instrument_fastapi(app: FastAPI) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument(app=app)
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed; skipping OTel instrumentation")


def try_register_prometheus(app: FastAPI, runtime: Any) -> None:
    try:
        from underwrite.prometheus_export import PrometheusMiddleware

        app.add_middleware(PrometheusMiddleware, runtime=runtime)
    except ImportError:
        logger.warning("prometheus_export module not found; Prometheus metrics disabled (install underwrite[serve])")


def create_app(
    runtime: Any,
    services: str = "mechanism,audit",
    rate_limit: int = 100,
    require_auth: bool = False,
    api_token: str | None = None,
    shutdown_timeout: int = 30,
) -> FastAPI:
    """Create a FastAPI application wrapping an underwrite Runtime.

    The returned app provides versioned endpoints under ``/v1/``:
    ``/v1/health``, ``/v1/metrics``, ``/v1/publish``, plus unversioned
    ``/healthz`` and ``/readyz`` for load-balancer probes.

    Args:
        runtime: An initialized underwrite ``Runtime`` instance.
        services: Comma-separated list of services to start.
        rate_limit: Max requests per second.
        require_auth: If ``True``, ``UNDERWRITE_API_TOKEN`` must be set
            and every request must carry ``Authorization: Bearer <token>``.
        api_token: The bearer token to require (overrides env var).
        shutdown_timeout: Graceful shutdown timeout in seconds.

    Returns:
        A configured FastAPI application.

    Raises:
        ValueError: If *require_auth* is ``True`` and no token is available.
    """
    import asyncio as asyncio_mod
    import time as time_mod

    token: str = api_token or os.environ.get("UNDERWRITE_API_TOKEN", "") or ""
    if require_auth and not token:
        raise ValueError("UNDERWRITE_API_TOKEN must be set when --require-auth is used")
    if not require_auth and not token:
        logger.warning("API authentication is DISABLED. Set UNDERWRITE_API_TOKEN or pass --require-auth in production.")

    app = FastAPI(title="underwrite", version=importlib.metadata.version("underwrite"))

    try_instrument_fastapi(app)
    try_register_prometheus(app, runtime)

    max_body_size: int = 1_048_576  # 1 MB

    @app.middleware("http")
    async def body_size_middleware(request: Request, call_next: Any) -> JSONResponse:
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > max_body_size:
            return __error_response(413, "request body too large")
        return await call_next(request)

    svc_list: list[str] = [s.strip() for s in services.split(",") if s.strip()]
    bucket_tokens: float = float(rate_limit)
    bucket_last: float = time_mod.monotonic()
    rate_lock: asyncio_mod.Lock = asyncio_mod.Lock()

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Any,
    ) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def auth_rate_limit_middleware(
        request: Request,
        call_next: Any,
    ) -> JSONResponse:
        if token:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return __error_response(401, "unauthorized")
            received = auth.removeprefix("Bearer ")
            if not hmac.compare_digest(received, token):
                return __error_response(401, "unauthorized")

        nonlocal bucket_tokens, bucket_last, rate_lock
        async with rate_lock:
            now = time_mod.monotonic()
            elapsed = now - bucket_last
            bucket_last = now
            bucket_tokens = min(float(rate_limit), bucket_tokens + elapsed * rate_limit)
            if bucket_tokens < 1.0:
                return __error_response(429, "rate limit exceeded")
            bucket_tokens -= 1.0
        return await call_next(request)

    @app.on_event("startup")
    async def startup() -> None:
        runtime.start(svc_list)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        import asyncio

        try:
            await asyncio.wait_for(
                asyncio.to_thread(runtime.stop),
                timeout=shutdown_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("runtime stop timed out after {}s", shutdown_timeout)

    # -- unversioned load-balancer probes ------------------------------------

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Kubernetes liveness probe."""
        status = runtime.health.status()
        return JSONResponse(
            status_code=200 if status.get("ok") else 503,
            content=status,
        )

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Kubernetes readiness probe."""
        status = runtime.health.status()
        return JSONResponse(
            status_code=200 if status.get("ok") else 503,
            content=status,
        )

    # -- versioned API -------------------------------------------------------

    @app.get(
        "/v1/health",
        summary="System health",
        description="Returns the health status of all registered subsystems "
        "(bus, store, services, etc.).  Useful for load balancer probes.",
        response_description="A dict mapping subsystem name to its health status.",
    )
    async def v1_health_endpoint() -> dict:
        return runtime.health.status()

    @app.get(
        "/v1/metrics",
        summary="Prometheus metrics",
        description="Exposes runtime and service metrics in Prometheus "
        "text-format (``text/plain; version=0.0.4``).  Requires the "
        "``underwrite[serve]`` extra.",
        response_description="Prometheus-format metrics text.",
        response_model=None,
    )
    async def v1_metrics_endpoint():
        try:
            from underwrite.prometheus_export import metrics_as_text

            return PlainTextResponse(
                metrics_as_text(runtime),
                media_type="text/plain; version=0.0.4",
            )
        except ImportError:
            return __error_response(501, "prometheus export not available; install underwrite[serve]")

    @app.post(
        "/v1/publish",
        summary="Publish domain event",
        description="Publishes a domain event to the runtime's event bus. "
        "The event is dispatched to all subscribed services.  Returns 202 "
        "on acceptance (fire-and-forget).",
        response_description="Confirmation that the event was accepted.",
    )
    async def v1_publish_event(request: Request) -> JSONResponse:
        body = await request.json()
        event_type = body.get("event_type", "")
        if not event_type or not __VALID_EVENT_TYPE_RE.match(event_type):
            return __error_response(400, "event_type is required")
        source = body.get("source", "")
        if not source or not __VALID_SOURCE_RE.match(source):
            return __error_response(
                400,
                "source is required and must match [a-z][a-z0-9_.-]+",
            )
        rt = runtime
        try:
            if hasattr(rt, "publish_as"):
                result = rt.publish_as(
                    source=source,
                    event_type=event_type,
                    payload=body.get("payload", {}),
                    correlation_id=body.get("correlation_id", ""),
                )
            else:
                result = None
                if hasattr(rt, "async_publish"):
                    await rt.async_publish(
                        event_type=event_type,
                        payload=body.get("payload", {}),
                        correlation_id=body.get("correlation_id", ""),
                    )
                else:
                    rt.publish(
                        event_type=event_type,
                        payload=body.get("payload", {}),
                        correlation_id=body.get("correlation_id", ""),
                    )
            return JSONResponse(status_code=202, content={"status": "accepted", "event_id": result or ""})
        except PermissionError as exc:
            return __error_response(403, str(exc))
        except ProtocolError:
            return __error_response(400, "invalid request")
        except Exception:
            logger.exception("publish failed")
            return __error_response(500, "internal server error")

    # -- legacy unversioned endpoints (deprecated) ---------------------------

    @app.get(
        "/health",
        include_in_schema=False,
    )
    async def health_endpoint() -> dict:
        return runtime.health.status()

    @app.get(
        "/metrics",
        include_in_schema=False,
        response_model=None,
    )
    async def metrics_endpoint():
        try:
            from underwrite.prometheus_export import metrics_as_text

            return PlainTextResponse(
                metrics_as_text(runtime),
                media_type="text/plain; version=0.0.4",
            )
        except ImportError:
            return __error_response(501, "prometheus export not available; install underwrite[serve]")

    return app
