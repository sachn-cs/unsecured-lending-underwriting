"""Tests for response caching decorator.

Item 122 from production roadmap.
"""

from __future__ import annotations

import pytest
from fastapi import Request

from ulu.api.cache import ResponseCache, cache_response


class TestResponseCache:
    def test_cache_miss_returns_none(self) -> None:
        cache = ResponseCache(default_ttl=1.0)
        req = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
        assert cache.get(req) is None

    def test_cache_hit_returns_value(self) -> None:
        cache = ResponseCache(default_ttl=1.0)
        req = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
        cache.set(req, {"data": 42})
        assert cache.get(req) == {"data": 42}

    def test_cache_expires_after_ttl(self) -> None:
        cache = ResponseCache(default_ttl=0.01)
        req = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
        cache.set(req, {"data": 42})
        import time

        time.sleep(0.02)
        assert cache.get(req) is None

    def test_cache_key_includes_query_params(self) -> None:
        cache = ResponseCache(default_ttl=1.0)
        req1 = Request({"type": "http", "method": "GET", "path": "/test", "query_string": b"a=1"})
        req2 = Request({"type": "http", "method": "GET", "path": "/test", "query_string": b"a=2"})
        cache.set(req1, "first")
        assert cache.get(req1) == "first"
        assert cache.get(req2) is None

    def test_clear_removes_all(self) -> None:
        cache = ResponseCache(default_ttl=1.0)
        req = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
        cache.set(req, {"data": 42})
        cache.clear()
        assert cache.get(req) is None


class TestCacheResponseDecorator:
    @pytest.mark.asyncio
    async def test_decorator_caches_result(self) -> None:
        call_count = 0

        @cache_response(ttl=1.0)
        async def endpoint(request: Request) -> dict:
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        req = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
        result1 = await endpoint(request=req)
        result2 = await endpoint(request=req)
        assert result1 == {"count": 1}
        assert result2 == {"count": 1}
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_decorator_without_request_calls_directly(self) -> None:
        call_count = 0

        @cache_response(ttl=1.0)
        async def no_request() -> dict:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        result = await no_request()
        assert result == {"ok": True}
        assert call_count == 1
