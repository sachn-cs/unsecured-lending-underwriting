"""FastAPI middleware for auth, metrics, and correlation IDs."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Injects X-Request-ID into response headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get("X-Request-ID", "")
        if not correlation_id:
            import uuid

            correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Adds X-Response-Time header."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Response-Time"] = f"{elapsed:.6f}"
        return response


class PayloadSizeMiddleware(BaseHTTPMiddleware):
    """Rejects requests with Content-Length exceeding 1 MB."""

    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_CONTENT_LENGTH:
            return Response(status_code=413, content=b"payload too large")
        return await call_next(request)
