"""Unit tests for query cache with TTL eviction."""

from __future__ import annotations

import time

from ulu.infra.query_cache import QueryCache


class TestQueryCache:
    def test_set_and_get(self) -> None:
        cache = QueryCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing(self) -> None:
        cache = QueryCache()
        assert cache.get("missing") is None

    def test_ttl_expiration(self) -> None:
        cache = QueryCache(default_ttl=0.01)
        cache.set("key1", "value1")
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_invalidate(self) -> None:
        cache = QueryCache()
        cache.set("key1", "value1")
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_invalidate_prefix(self) -> None:
        cache = QueryCache()
        cache.set("prefix:a", 1)
        cache.set("prefix:b", 2)
        cache.set("other:c", 3)
        cache.invalidate_prefix("prefix:")
        assert cache.get("prefix:a") is None
        assert cache.get("prefix:b") is None
        assert cache.get("other:c") == 3

    def test_clear(self) -> None:
        cache = QueryCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_cached_decorator(self) -> None:
        cache = QueryCache()
        call_count = 0

        @cache.cached(ttl=60.0)
        def expensive(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10
        assert call_count == 1
        assert expensive(6) == 12
        assert call_count == 2
