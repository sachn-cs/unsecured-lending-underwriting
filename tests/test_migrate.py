"""Tests for MigrationPlan."""

from __future__ import annotations

import pytest

from underwrite.__exceptions__ import MigrationError
from underwrite.__migrate__ import Migration, MigrationPlan, default_plan


class TestMigrationPlan:

    def test_empty_plan(self) -> None:
        plan = MigrationPlan()
        assert plan.latest_version == 0
        assert plan.pending(set()) == []

    def test_add_and_pending(self) -> None:
        plan = MigrationPlan()
        plan.add(Migration(version=1, description="init"))
        plan.add(Migration(version=2, description="add_table"))
        pending = plan.pending({1})
        assert len(pending) == 1
        assert pending[0].version == 2

    def test_all_pending_when_none_applied(self) -> None:
        plan = MigrationPlan()
        plan.add(Migration(version=1, description="v1"))
        plan.add(Migration(version=2, description="v2"))
        assert len(plan.pending(set())) == 2

    def test_duplicate_version_raises(self) -> None:
        plan = MigrationPlan()
        plan.add(Migration(version=1, description="first"))
        with pytest.raises(MigrationError,
                           match="duplicate migration version 1"):
            plan.add(Migration(version=1, description="dupe"))

    def test_latest_version(self) -> None:
        plan = MigrationPlan()
        plan.add(Migration(version=1, description="a"))
        plan.add(Migration(version=3, description="c"))
        plan.add(Migration(version=2, description="b"))
        assert plan.latest_version == 3

    def test_default_plan_has_migrations(self) -> None:
        plan = default_plan()
        assert plan.latest_version >= 1
        assert len(plan.pending(set())) >= 1
