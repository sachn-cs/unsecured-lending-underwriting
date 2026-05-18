"""Portfolio summary materialized view for fast read queries.

Item 117 from production roadmap.
"""

from __future__ import annotations

import dataclasses
import datetime

from ulu.infra.logging import logger


@dataclasses.dataclass
class PortfolioSummary:
    """Pre-computed summary for a user portfolio."""

    user_id: str
    total_principal: float
    total_earned_credit: float
    total_outstanding: float
    total_recovered: float
    total_defaults: float
    updated_at: datetime.datetime


class PortfolioSummaryService:
    """Maintains an in-memory materialized view of portfolio summaries.

    Production should replace the dict with a PostgreSQL materialized view
    refreshed concurrently.
    """

    def __init__(self) -> None:
        self._summaries: dict[str, PortfolioSummary] = {}
        self._last_refresh: datetime.datetime | None = None

    def refresh(
        self,
        principal: dict[str, float],
        earned: dict[str, float],
        recovered: dict[str, float] | None = None,
        defaults: dict[str, float] | None = None,
    ) -> None:
        """Recomputes summaries from raw accounting dicts."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        users = set(principal.keys()) | set(earned.keys())
        self._summaries.clear()
        for user in users:
            p = principal.get(user, 0.0)
            e = earned.get(user, 0.0)
            r = recovered.get(user, 0.0) if recovered else 0.0
            d = defaults.get(user, 0.0) if defaults else 0.0
            self._summaries[user] = PortfolioSummary(
                user_id=user,
                total_principal=p,
                total_earned_credit=e,
                total_outstanding=max(0.0, p - e - r),
                total_recovered=r,
                total_defaults=d,
                updated_at=now,
            )
        self._last_refresh = now
        logger.info("portfolio_summary_refreshed", user_count=len(users))

    def get(self, user_id: str) -> PortfolioSummary | None:
        return self._summaries.get(user_id)

    def list_all(self) -> list[PortfolioSummary]:
        return list(self._summaries.values())

    def total_outstanding(self) -> float:
        return sum(s.total_outstanding for s in self._summaries.values())

    def total_principal(self) -> float:
        return sum(s.total_principal for s in self._summaries.values())

    def total_earned_credit(self) -> float:
        return sum(s.total_earned_credit for s in self._summaries.values())

    def total_defaults(self) -> float:
        return sum(s.total_defaults for s in self._summaries.values())

    def summary(self) -> dict[str, float | int]:
        return {
            "user_count": len(self._summaries),
            "total_principal": self.total_principal(),
            "total_earned_credit": self.total_earned_credit(),
            "total_outstanding": self.total_outstanding(),
            "total_defaults": self.total_defaults(),
        }
