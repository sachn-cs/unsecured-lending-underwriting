"""Unit tests for query cache decorator."""

from __future__ import annotations

from ulu.infra.query_cache import QueryCache


class DummyRepository:
    def __init__(self) -> None:
        self.call_count = 0
        self.cache = QueryCache(redis_url=None)

    @QueryCache(redis_url=None).cached(ttl=30)
    async def get_user(self, user_id: str) -> dict[str, str]:
        self.call_count += 1
        return {"id": user_id, "name": "test"}


class TestQueryCache:
    async def test_cache_miss(self) -> None:
        repo = DummyRepository()
        result = await repo.get_user("u1")
        assert result == {"id": "u1", "name": "test"}
        assert repo.call_count == 1

    async def test_no_redis_always_miss(self) -> None:
        cache = QueryCache(redis_url=None)

        async def fn() -> str:
            return "hello"

        decorated = cache.cached()(fn)
        assert await decorated() == "hello"
