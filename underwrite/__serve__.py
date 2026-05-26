"""HTTP server for the underwrite Runtime.

Provides health, metrics, and event-publishing endpoints with
optional bearer token authentication.
"""

from __future__ import annotations

__all__ = [
    "create_app",
]

import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger(__name__)


def _try_instrument_fastapi(app: FastAPI) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().instrument(app=app)
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed; skipping OTel instrumentation")


def _try_register_prometheus(app: FastAPI, runtime: Any) -> None:
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
    api_token: str = "",
) -> FastAPI:
    """Create a FastAPI application wrapping an underwrite Runtime.

    The returned app provides ``/health`` and ``/metrics`` endpoints.

    Args:
        runtime: An initialised underwrite ``Runtime`` instance.
        services: Comma-separated list of services to start.
        rate_limit: Max requests per second.
        require_auth: If ``True``, ``UNDERWRITE_API_TOKEN`` must be set
            and every request must carry ``Authorization: Bearer <token>``.
        api_token: The bearer token to require (overrides env var).

    Returns:
        A configured FastAPI application.

    Raises:
        ValueError: If *require_auth* is ``True`` and no token is available.
    """
    import time as _time

    token: str = api_token or os.environ.get("UNDERWRITE_API_TOKEN", "")
    if require_auth and not token:
        raise ValueError(
            "UNDERWRITE_API_TOKEN must be set when --require-auth is used"
        )

    app = FastAPI(title="underwrite", version="0.1.0")

    _try_instrument_fastapi(app)
    _try_register_prometheus(app, runtime)

    _svc_list: list[str] = [s.strip() for s in services.split(",") if s.strip()]
    _bucket_tokens: float = float(rate_limit)
    _bucket_last: float = _time.monotonic()

    @app.middleware("http")
    async def _auth_rate_limit_middleware(
        request: Request,
        call_next: Any,
    ) -> JSONResponse:
        if token:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") != token:
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized"},
                )

        nonlocal _bucket_tokens, _bucket_last
        now = _time.monotonic()
        elapsed = now - _bucket_last
        _bucket_last = now
        _bucket_tokens = min(float(rate_limit), _bucket_tokens + elapsed * rate_limit)
        if _bucket_tokens < 1.0:
            return JSONResponse(
                status_code=429,
                content={"error": "rate limit exceeded"},
            )
        _bucket_tokens -= 1.0
        return await call_next(request)

    @app.on_event("startup")
    async def startup() -> None:
        runtime.start(_svc_list)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        runtime.stop()

    @app.get("/health")
    async def health_endpoint() -> dict:
        return runtime.health.status()

    @app.get("/metrics")
    async def metrics_endpoint() -> JSONResponse | PlainTextResponse:
        try:
            from underwrite.prometheus_export import metrics_as_text
            return PlainTextResponse(
                metrics_as_text(runtime),
                media_type="text/plain; version=0.0.4",
            )
        except ImportError:
            return JSONResponse(
                status_code=501,
                content={"error": "prometheus export not available; install underwrite[serve]"},
            )

    @app.post("/publish")
    async def publish_event(request: Request) -> JSONResponse:
        body = await request.json()
        event_type = body.get("event_type", "")
        if not event_type:
            return JSONResponse(status_code=400, content={"error": "event_type is required"})
        rt = runtime
        try:
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
            return JSONResponse(status_code=202, content={"status": "accepted"})
        except Exception as exc:
            logger.exception("publish failed")
            return JSONResponse(status_code=500, content={"error": str(exc)})

    return app
