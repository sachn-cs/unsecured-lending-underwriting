# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Schema migration engine for the underwrite platform.

Migrations are ordered by version. Each migration is a tuple of SQL
statements to execute inside a single transaction. The engine records
which versions have been applied in a ``migrations`` table and only
runs the pending ones. Statements are written for SQLite (the only
supported backend); the engine itself is backend-aware in that it
records applied versions transactionally so a crash mid-migration
cannot leave the schema in a partially-applied state.
"""

from __future__ import annotations

__all__ = [
    "Migration",
    "MigrationPlan",
    "default_plan",
]

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from underwrite.exceptions import MigrationError


@dataclass(frozen=True, slots=True)
class Migration:
    """A single schema migration — a tuple of SQL statements."""

    version: int
    description: str
    statements: tuple[str, ...] = ()
    fn: Callable[[Any], None] | None = None


class MigrationPlan:
    """Ordered sequence of schema migrations."""

    def __init__(self) -> None:
        self.migrations: dict[int, Migration] = {}

    def add(self, migration: Migration) -> None:
        """Registers a migration.

        Args:
            migration: The migration to register.

        Raises:
            MigrationError: If a migration with the same version already exists.
        """
        if migration.version in self.migrations:
            raise MigrationError(f"duplicate migration version {migration.version}")
        self.migrations[migration.version] = migration

    def pending(self, applied: set[int]) -> list[Migration]:
        """Returns migrations that have not yet been applied, in version order.

        Args:
            applied: Set of version numbers already applied.

        Returns:
            Sorted list of pending migrations.
        """
        return [self.migrations[v] for v in sorted(self.migrations) if v not in applied]

    @property
    def latest_version(self) -> int:
        """Returns the highest registered migration version, or 0."""
        return max(self.migrations.keys()) if self.migrations else 0


def default_plan() -> MigrationPlan:
    """Returns the default migration plan for the platform."""
    plan = MigrationPlan()
    plan.add(
        Migration(
            version=1,
            description="Initial store schema — key-value table",
            statements=(
                "CREATE TABLE IF NOT EXISTS store (  key TEXT PRIMARY KEY,  value BLOB NOT NULL)",
                "CREATE TABLE IF NOT EXISTS migrations ("
                "  version INTEGER PRIMARY KEY,"
                "  description TEXT NOT NULL,"
                "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")",
            ),
        )
    )
    plan.add(
        Migration(
            version=2,
            description="Message dead-letter queue",
            statements=(
                "CREATE TABLE IF NOT EXISTS dead_letters ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  event_id TEXT NOT NULL,"
                "  event_type TEXT NOT NULL,"
                "  source TEXT NOT NULL,"
                "  payload TEXT,"
                "  error TEXT NOT NULL,"
                "  failed_at TEXT NOT NULL DEFAULT (datetime('now')),"
                "  replayed INTEGER NOT NULL DEFAULT 0"
                ")",
            ),
        )
    )
    plan.add(
        Migration(
            version=3,
            description="Metrics snapshot table",
            statements=(
                "CREATE TABLE IF NOT EXISTS metrics_snapshots ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  data TEXT NOT NULL,"
                "  captured_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")",
            ),
        )
    )
    return plan
