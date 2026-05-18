"""In-memory query cache with TTL eviction for expensive read operations.

Item 119 from production roadmap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from ulu.infra.logging import logger

T = TypeVar("T")


class QueryCache:
    """Simple TTL cache for read query results.

    Production should replace this with Redis or Memcached for
    cross-instance consistency.
    """

    def __init__(self, default_ttl: float = 60.0) -> None:
        self.default_ttl = default_ttl
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        value, expiry = self._store[key]
        if time.time() > expiry:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        expiry = time.time() + (ttl or self.default_ttl)
        self._store[key] = (value, expiry)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()

    def cached(self, ttl: float | None = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator that caches function results by positional args."""
        def decorator(fn: Callable[..., T]) -> Callable[..., T]:
            def wrapper(*args: Any, **kwargs: Any) -> T:
                cache_key = f"{fn.__name__}:{hash(args)}:{hash(tuple(sorted(kwargs.items())))}"
                cached = self.get(cache_key)
                if cached is not None:
                    logger.debug("query_cache_hit", key=cache_key)
                    return cached
                result = fn(*args, **kwargs)
                self.set(cache_key, result, ttl)
                logger.debug("query_cache_set", key=cache_key)
                return result
            return wrapper
        return decorator
