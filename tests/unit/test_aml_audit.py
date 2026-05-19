"""Tests for AML audit trail repository.

Item 102 from production roadmap.
"""

from __future__ import annotations

import pytest

from ulu.infra.models import AmlAuditRecord
from ulu.infra.repositories import AmlAuditRepository


class TestAmlAuditRepository:
    @pytest.mark.asyncio
    async def test_create_and_get(self, async_session) -> None:
        repo = AmlAuditRepository(async_session)
        record = AmlAuditRecord(
            user_id="user-1",
            screen_type="sanctions",
            source="OFAC",
            status_before="clear",
            status_after="flagged",
            reason="matched_list",
        )
        created = await repo.create(record)
        assert created.id is not None
        assert created.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_list_by_user(self, async_session) -> None:
        repo = AmlAuditRepository(async_session)
        await repo.create(
            AmlAuditRecord(
                user_id="user-a",
                screen_type="sanctions",
                source="OFAC",
                status_before="clear",
                status_after="flagged",
                reason="hit",
            )
        )
        await repo.create(
            AmlAuditRecord(
                user_id="user-b",
                screen_type="pep",
                source="UN",
                status_before="clear",
                status_after="flagged",
                reason="hit",
            )
        )
        results = await repo.list_by_user("user-a")
        assert len(results) == 1
        assert results[0].user_id == "user-a"
