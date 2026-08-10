# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Protocol governance - parameter management and proposals.

Maintains protocol-level parameters (protocol_rate, max_delegation_rate,
dlg_cap_ratio, ltv_ratio, min_base_budget) within defined ranges and
processes GOVERNANCE_PROPOSAL events to update them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import Dependencies, StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Disk, InMemory, Sqlite, Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer
from underwrite.validate import PayloadValidator

DEFAULT_PARAM_RANGES: dict[str, tuple[float, float]] = {
    "protocol_rate": (0.0, 1.0),
    "max_delegation_rate": (0.0, 1.0),
    "dlg_cap_ratio": (0.0, 1.0),
    "ltv_ratio": (0.0, 1.0),
    "min_base_budget": (0.0, float("inf")),
}

DEFAULT_PARAM_DEFAULTS: dict[str, float] = {
    "protocol_rate": 0.10,
    "max_delegation_rate": 0.05,
    "dlg_cap_ratio": 0.05,
    "ltv_ratio": 0.75,
    "min_base_budget": 1000.0,
}


@dataclass(frozen=True, slots=True)
class GovernanceConfig:
    """Typed configuration for Handler.

    Replaces the previous ``kwargs.pop("param_ranges", ...)`` pattern:
    callers now pass a GovernanceConfig (or its fields are extracted
    from kwargs via a constructor that does not mutate the caller's
    mapping).
    """

    param_ranges: dict[str, list[float]] = field(default_factory=dict)
    param_defaults: dict[str, float] = field(default_factory=dict)


class Handler(StatefulService):
    """Manages protocol parameters and handles governance proposals."""

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
        """Initialize the governance service with default parameter values.

        Args:
            **kwargs: Forwarded to Core.__init__.
        """
        config = GovernanceConfig(
            param_ranges=kwargs.pop("param_ranges", {}),
            param_defaults=kwargs.pop("param_defaults", {}),
        )
        raw_ranges = config.param_ranges
        raw_defaults = config.param_defaults
        self.ranges_dict: dict[str, tuple[float, float]] = (
            {
                k: (float(v[0]), float(v[1]))
                for k, v in raw_ranges.items()
                if isinstance(v, list | tuple) and len(v) == 2
            }
            if raw_ranges
            else DEFAULT_PARAM_RANGES
        )
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
        self.params_storage: dict[str, float] = raw_defaults.copy() if raw_defaults else DEFAULT_PARAM_DEFAULTS.copy()
        self.repo: TypedStoreRepository[dict[str, float]] = self.store_repo("params", dict)

    def start(self) -> None:
        """Load persisted parameters when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.params_storage = loaded

    def handle(self, event: Message) -> None:
        """Process a governance proposal to update a protocol parameter.

        Validates the parameter name and value range before applying.

        Args:
            event: The incoming event. Only GOVERNANCE_PROPOSAL events
                are processed.
        """
        if event.event_type != Type.GOVERNANCE_PROPOSAL:
            return
        p = event.payload
        param: str = PayloadValidator().non_empty(p, "param")
        value: float = PayloadValidator().finite(p, "value")
        if param not in self.params_storage:
            logger.warning("governance proposal for unknown param {!r} ignored", param)
            return
        lo, hi = self.ranges_dict[param]
        if not (lo <= value <= hi):
            logger.warning(
                "governance proposal for {!r} value {} outside range [{}, {}]",
                param,
                value,
                lo,
                hi,
            )
            return
        with self.state_lock:
            self.params_storage[param] = value
            self.repo.save(self.params_storage)
        self.emit(
            Type.GOVERNANCE_EXECUTED,
            {
                "param": param,
                "value": value,
            },
            correlation_id=event.correlation_id,
        )

    @property
    def params(self) -> dict[str, float]:
        """Return a snapshot of all current protocol parameters.

        Returns:
            Dict of parameter name to value.
        """
        with self.state_lock:
            return dict(self.params_storage)

    def health_check(self) -> dict[str, Any]:
        """Run governance-specific health checks.

        Returns:
            Health dict with active param count.
        """
        with self.state_lock:
            return {
                **super().health_check(),
                "param_count": len(self.params_storage),
            }
