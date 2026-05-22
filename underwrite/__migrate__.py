"""Schema migration engine for the underwrite platform.

Migrations are ordered by version number.  Each migration is a SQL
statement (for SQL stores) or a callable (for any store).  The engine
tracks which versions have been applied and runs pending ones.
"""

from __future__ import annotations

__all__ = [
    "Migration",
    "MigrationPlan",
    "default_plan",
]

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from underwrite.__exceptions__ import MigrationError


@dataclass
class Migration:
    """A single schema migration — SQL statements or a callable."""

    version: int
    description: str
    statements: list[str] = field(default_factory=list)
    fn: Callable[[Any], None] | None = None


class MigrationPlan:
    """Ordered sequence of schema migrations."""

    def __init__(self) -> None:
        self.__migrations: dict[int, Migration] = {}

    def add(self, migration: Migration) -> None:
        """Registers a migration.

        Args:
            migration: The migration to register.

        Raises:
            MigrationError: If a migration with the same version already exists.
        """
        if migration.version in self.__migrations:
            raise MigrationError(
                f"duplicate migration version {migration.version}")
        self.__migrations[migration.version] = migration

    def pending(self, applied: set[int]) -> list[Migration]:
        """Returns migrations that have not yet been applied, in version order.

        Args:
            applied: Set of version numbers already applied.

        Returns:
            Sorted list of pending migrations.
        """
        return [
            self.__migrations[v]
            for v in sorted(self.__migrations)
            if v not in applied
        ]

    @property
    def latest_version(self) -> int:
        """Returns the highest registered migration version, or 0."""
        return max(self.__migrations.keys()) if self.__migrations else 0


def default_plan() -> MigrationPlan:
    """Returns the default migration plan for the platform."""
    plan = MigrationPlan()
    plan.add(
        Migration(
            version=1,
            description="Initial store schema — key-value table",
            statements=[
                """CREATE TABLE IF NOT EXISTS store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )""",
                """CREATE TABLE IF NOT EXISTS migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )""",
            ],
        ))
    plan.add(
        Migration(
            version=2,
            description="Event dead-letter queue",
            statements=[
                """CREATE TABLE IF NOT EXISTS dead_letters (
                id SERIAL PRIMARY KEY,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                payload TEXT,
                error TEXT NOT NULL,
                failed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                replayed BOOLEAN NOT NULL DEFAULT FALSE
            )""",
            ],
        ))
    plan.add(
        Migration(
            version=3,
            description="Metrics snapshot table",
            statements=[
                """CREATE TABLE IF NOT EXISTS metrics_snapshots (
                id SERIAL PRIMARY KEY,
                data JSONB NOT NULL,
                captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )""",
            ],
        ))
    return plan
