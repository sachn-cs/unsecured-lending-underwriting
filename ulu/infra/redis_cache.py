"""Redis-backed idempotency cache with in-memory fallback.

Item 120 from production roadmap.
"""

from __future__ import annotations

import json
from typing import Any

from ulu.infra.logging import logger


class RedisIdempotencyCache:
    """Redis-backed idempotency store for multi-instance deployments.

    Falls back to in-memory dict when Redis is unavailable.
    """

    def __init__(self, redis_url: str | None = None, ttl_seconds: int = 3600) -> None:
        self.redis_url = redis_url
        self.ttl = ttl_seconds
        self._fallback: dict[str, tuple[str, dict[str, Any]]] = {}
        self._client: Any | None = None
        if redis_url:
            try:
                import redis.asyncio as aioredis

                self._client = aioredis.from_url(redis_url, decode_responses=True)
                logger.info("redis_idempotency_connected", redis_url=redis_url)
            except Exception as exc:
                logger.warning("redis_idempotency_fallback", error=str(exc))
                self._client = None

    def _make_key(self, operation_name: str, idempotency_key: str) -> str:
        return f"idempotency:{operation_name}:{idempotency_key}"

    async def get(self, operation_name: str, idempotency_key: str) -> tuple[str, dict[str, Any]] | None:
        key = self._make_key(operation_name, idempotency_key)
        if self._client is not None:
            try:
                raw = await self._client.get(key)
                if raw:
                    payload = json.loads(raw)
                    return payload["hash"], payload["response"]
            except Exception as exc:
                logger.warning("redis_get_failed", error=str(exc))
        return self._fallback.get(key)

    async def set(
        self,
        operation_name: str,
        idempotency_key: str,
        payload_hash: str,
        response: dict[str, Any],
    ) -> None:
        key = self._make_key(operation_name, idempotency_key)
        value = json.dumps({"hash": payload_hash, "response": response})
        if self._client is not None:
            try:
                await self._client.setex(key, self.ttl, value)
                return
            except Exception as exc:
                logger.warning("redis_set_failed", error=str(exc))
        self._fallback[key] = (payload_hash, response)

    async def clear(self) -> None:
        if self._client is not None:
            try:
                await self._client.flushdb()
            except Exception as exc:
                logger.warning("redis_clear_failed", error=str(exc))
        self._fallback.clear()
