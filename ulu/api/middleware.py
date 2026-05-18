"""FastAPI middleware for auth, metrics, and correlation IDs."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

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


class CspMiddleware(BaseHTTPMiddleware):
    """Adds Content-Security-Policy header to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
        return response


class ResponseCacheMiddleware(BaseHTTPMiddleware):
    """Caches GET responses for configured paths with TTL eviction."""

    DEFAULT_TTL_SECONDS = 30.0

    def __init__(self, app: Any, cached_paths: set[str] | None = None, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        super().__init__(app)
        self.cached_paths = cached_paths or {"/admin/graph", "/admin/utilization", "/admin/solvency"}
        self.ttl = ttl
        self._cache: dict[str, tuple[bytes, float]] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method != "GET" or request.url.path not in self.cached_paths:
            return await call_next(request)
        cache_key = request.url.path
        now = time.time()
        if cache_key in self._cache:
            body, ts = self._cache[cache_key]
            if now - ts < self.ttl:
                return Response(content=body, status_code=200, headers={"X-Cache": "HIT"})
        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                body += chunk
            else:
                body += chunk.encode("utf-8")
        self._cache[cache_key] = (body, now)
        return Response(content=body, status_code=response.status_code, headers=dict(response.headers))


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs all incoming requests and outgoing responses (sanitized)."""

    SENSITIVE_KEYS = {"password", "token", "secret", "jwt", "api_key", "authorization"}

    def _sanitize(self, data: dict) -> dict:
        """Redacts sensitive fields from logged payloads."""
        if not isinstance(data, dict):
            return data
        sanitized: dict = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in self.SENSITIVE_KEYS:
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize(value)
            else:
                sanitized[key] = value
        return sanitized

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from ulu.infra.logging import logger

        correlation_id = getattr(request.state, "correlation_id", "")
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            correlation_id=correlation_id,
        )
        response = await call_next(request)
        logger.info(
            "http_response",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            correlation_id=correlation_id,
        )
        return response
