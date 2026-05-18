"""Integration tests for cursor-based pagination."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ulu.infra.models import AuditEvent
from ulu.infra.repositories import AuditEventRepository, BaseRepository


class TestCursorPagination:
    @pytest.mark.asyncio
    async def test_encode_decode_cursor(self) -> None:
        assert BaseRepository._decode_cursor(None) == (0, 100)
        cursor = BaseRepository._encode_cursor(10, 50)
        assert BaseRepository._decode_cursor(cursor) == (10, 50)

    @pytest.mark.asyncio
    async def test_audit_event_cursor_pagination(self, async_session: AsyncSession) -> None:
        repo = AuditEventRepository(async_session)
        for i in range(5):
            event = AuditEvent(seq=i + 1, event_type="test", payload={"i": i})
            async_session.add(event)
        await async_session.flush()

        page1 = await repo.list_by_type_cursor("test", cursor=None)
        assert len(page1["items"]) == 5
        assert page1["has_more"] is False
        assert page1["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_audit_event_cursor_has_more(self, async_session: AsyncSession) -> None:
        repo = AuditEventRepository(async_session)
        for i in range(5):
            event = AuditEvent(seq=i + 1, event_type="test", payload={"i": i})
            async_session.add(event)
        await async_session.flush()

        page1 = await repo.list_by_type_cursor("test", cursor=BaseRepository._encode_cursor(0, 2))
        assert len(page1["items"]) == 2
        assert page1["has_more"] is True
        assert page1["next_cursor"] is not None

        page2 = await repo.list_by_type_cursor("test", cursor=page1["next_cursor"])
        assert len(page2["items"]) == 2
        assert page2["has_more"] is True

        page3 = await repo.list_by_type_cursor("test", cursor=page2["next_cursor"])
        assert len(page3["items"]) == 1
        assert page3["has_more"] is False
