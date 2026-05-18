"""Redis-backed read query cache for repository hot paths.

Item 119 from production roadmap.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable
from typing import Any

from ulu.infra.logging import logger


class QueryCache:
    """Method-level cache decorator using Redis with TTL fallback."""

    def __init__(self, redis_url: str | None = None, default_ttl: int = 60) -> None:
        self.default_ttl = default_ttl
        self._client: Any | None = None
        if redis_url:
            try:
                import redis.asyncio as aioredis

                self._client = aioredis.from_url(redis_url, decode_responses=True)
                logger.info("query_cache_connected", redis_url=redis_url)
            except Exception as exc:
                logger.warning("query_cache_fallback", error=str(exc))

    def _key(self, fn_name: str, args: tuple, kwargs: dict) -> str:
        blob = json.dumps({"fn": fn_name, "args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return f"query_cache:{fn_name}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"

    def cached(self, ttl: int | None = None) -> Callable:
        """Decorator that caches the return value of an async function."""
        _ttl = ttl or self.default_ttl

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                if self._client is None:
                    return await fn(*args, **kwargs)
                key = self._key(fn.__name__, args[1:], kwargs)  # skip self
                try:
                    raw = await self._client.get(key)
                    if raw:
                        return json.loads(raw)
                except Exception as exc:
                    logger.warning("query_cache_get_failed", error=str(exc))
                result = await fn(*args, **kwargs)
                try:
                    await self._client.setex(key, _ttl, json.dumps(result, default=str))
                except Exception as exc:
                    logger.warning("query_cache_set_failed", error=str(exc))
                return result

            return wrapper

        return decorator
