"""Unit tests for Redis idempotency cache with in-memory fallback."""

from __future__ import annotations

import pytest

from ulu.infra.redis_cache import RedisIdempotencyCache


class TestRedisIdempotencyCache:
    @pytest.fixture
    def cache(self) -> RedisIdempotencyCache:
        return RedisIdempotencyCache(redis_url=None, ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_set_and_get_fallback(self, cache: RedisIdempotencyCache) -> None:
        await cache.set("op1", "key1", "hash1", {"status": "ok"})
        result = await cache.get("op1", "key1")
        assert result is not None
        assert result[0] == "hash1"
        assert result[1] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_missing(self, cache: RedisIdempotencyCache) -> None:
        result = await cache.get("op1", "missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_fallback(self, cache: RedisIdempotencyCache) -> None:
        await cache.set("op1", "key1", "hash1", {"status": "ok"})
        await cache.clear()
        assert await cache.get("op1", "key1") is None

    def test_make_key(self, cache: RedisIdempotencyCache) -> None:
        key = cache._make_key("seed", "uuid-123")
        assert key == "idempotency:seed:uuid-123"
