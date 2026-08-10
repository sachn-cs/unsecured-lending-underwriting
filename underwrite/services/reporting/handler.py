# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""RBI regulatory reporting — generates reports from audit data.

Tracks portfolio-level metrics and NPA bucket-wise breakdowns
for regulatory reporting under RBI Master Circulars.
"""

from __future__ import annotations

from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.local import LocalBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.message import Message, Type
from underwrite.metrics import Collector, SystemClock
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store, InMemory, Disk, Sqlite
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator


class Handler(StatefulService):
    """Generates regulatory reports (RBI, internal) from the audit trail.

    Accumulates portfolio-wide counters as well as NPA bucket-wise
    distributions (standard, substandard, doubtful, loss) so that
    provisioning coverage ratios and portfolio health can be reported.
    """

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: Store | InMemory | Disk | Sqlite,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the reporting service with empty counters."""
        deps = Dependencies(
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        super().__init__(
            name=name,
            bus=deps.bus,
            store=deps.store,
            metrics=deps.metrics,
            health=deps.health,
            authz=deps.authz,
            tracer=deps.tracer,
            saga=deps.saga,
            supervisor=deps.supervisor,
            secrets_manager=deps.secrets_manager,
            max_concurrent=deps.max_concurrent,
        )
        self.clock: SystemClock = SystemClock()
        self.originations: int = 0
        self.defaults: int = 0
        self.total_principal: float = 0.0
        self.bucket_counts: dict[str, int] = {
            "standard": 0,
            "substandard": 0,
            "doubtful": 0,
            "loss": 0,
        }
        self.bucket_principals: dict[str, float] = {
            "standard": 0.0,
            "substandard": 0.0,
            "doubtful": 0.0,
            "loss": 0.0,
        }
        self.provisioning_total: float = 0.0
        self.repo: TypedStoreRepository[dict[str, Any]] = self.store_repo("counters", dict)

    def start(self) -> None:
        """Load persisted counters when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.originations = loaded.get("originations", 0)
            self.defaults = loaded.get("defaults", 0)
            self.total_principal = loaded.get("total_principal", 0.0)

    def handle(self, event: Message) -> None:
        """Process events to update portfolio metrics.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == Type.LOAN_ORIGINATED:
            with self.state_lock:
                self.originations += 1
                self.total_principal += PayloadValidator().finite(event.payload, "principal")
                self.sync()
        elif event.event_type == Type.DEFAULT_OCCURRED:
            with self.state_lock:
                self.defaults += 1
                self.sync()
        elif event.event_type == Type.NPA_BUCKET_CHANGED:
            self.track_bucket_change(event)
        elif event.event_type == Type.PROVISIONING_COMPUTED:
            self.track_provisioning(event)

    def track_bucket_change(self, event: Message) -> None:
        """Update bucket-wise counters when NPA classification changes.

        Args:
            event: The NPA_BUCKET_CHANGED event.
        """
        borrower: str = event.payload.get("borrower", "")
        bucket: str = event.payload.get("bucket", "standard")
        if not borrower or bucket not in self.bucket_counts:
            return
        with self.state_lock:
            self.bucket_counts[bucket] = self.bucket_counts.get(bucket, 0) + 1

    def track_provisioning(self, event: Message) -> None:
        """Track total provisioning amount.

        Args:
            event: The PROVISIONING_COMPUTED event.
        """
        amount: float = PayloadValidator().finite(event.payload, "provisioning_amount", 0.0)
        bucket: str = event.payload.get("bucket", "")
        principal: float = PayloadValidator().finite(event.payload, "outstanding", 0.0)
        if bucket not in self.bucket_principals:
            return
        with self.state_lock:
            self.bucket_principals[bucket] = principal
            self.provisioning_total += amount

    def generate_report(self, report_type: str = "portfolio_summary") -> dict[str, Any]:
        """Generate a regulatory report from accumulated metrics.

        Args:
            report_type: Type of report (default "portfolio_summary").

        Returns:
            Dict with report_type, generated_at, total_originations,
            total_defaults, total_principal_originated, default_rate,
            and portfolio health metrics.
        """
        return {
            "report_type": report_type,
            "generated_at": self.clock.iso(),
            "total_originations": self.originations,
            "total_defaults": self.defaults,
            "total_principal_originated": self.total_principal,
            "default_rate": self.defaults / max(self.originations, 1),
        }

    def generate_npa_report(self) -> dict[str, Any]:
        """Generate an NPA-specific regulatory report.

        Per RBI norms the NPA ratio is NPA outstanding over total
        outstanding, not over cumulative originations.

        Returns:
            Dict with bucket-wise counts, outstanding principals, and
            provisioning coverage information.
        """
        with self.state_lock:
            npa_principal = (
                self.bucket_principals.get("substandard", 0.0)
                + self.bucket_principals.get("doubtful", 0.0)
                + self.bucket_principals.get("loss", 0.0)
            )
            outstanding = sum(self.bucket_principals.values()) or 1.0
            return {
                "report_type": "npa_detailed",
                "generated_at": self.clock.iso(),
                "bucket_counts": self.bucket_counts,
                "bucket_principals": self.bucket_principals,
                "npa_principal": npa_principal,
                "npa_ratio": round(npa_principal / outstanding, 6),
                "total_provisioning": round(self.provisioning_total, 2),
                "provisioning_coverage_ratio": round(self.provisioning_total / max(npa_principal, 1.0), 6),
            }

    def sync(self) -> None:
        """Persist the in-memory counters to the shared store."""
        self.repo.save(
            {
                "originations": self.originations,
                "defaults": self.defaults,
                "total_principal": self.total_principal,
            }
        )
