"""FastAPI response caching decorator for read-heavy endpoints.

Item 122 from production roadmap.
"""

from __future__ import annotations

import functools
import hashlib
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request


class ResponseCache:
    """In-memory TTL cache for endpoint responses.

    Production replaces this with Redis-backed caching.
    """

    def __init__(self, default_ttl: float = 30.0) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def _key(self, request: Request) -> str:
        """Builds a cache key from request path and query params."""
        scope = request.scope
        parts = [scope.get("method", ""), scope.get("path", "")]
        query = scope.get("query_string", b"").decode("utf-8")
        if query:
            parts.append(query)
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, request: Request) -> Any | None:
        key = self._key(request)
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.time() > expiry:
            self._store.pop(key, None)
            return None
        return value

    def set(self, request: Request, value: Any, ttl: float | None = None) -> None:
        key = self._key(request)
        expiry = time.time() + (ttl if ttl is not None else self._default_ttl)
        self._store[key] = (value, expiry)

    def clear(self) -> None:
        self._store.clear()


_response_cache = ResponseCache()


def cache_response(ttl: float = 30.0) -> Callable:
    """Decorator that caches endpoint responses by request path + query.

    Usage:
        @router.get("/admin/utilization")
        @cache_response(ttl=30.0)
        async def admin_utilization(...):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            if request is None:
                return await func(*args, **kwargs)

            cached = _response_cache.get(request)
            if cached is not None:
                return cached

            result = await func(*args, **kwargs)
            _response_cache.set(request, result, ttl=ttl)
            return result

        return wrapper

    return decorator
