# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Delegation graph queries - read-only access to protocol state."""

from __future__ import annotations

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
from underwrite.services.base import Core, Dependencies
from underwrite.services.mechanism.graph import to_money
from underwrite.store import StoreBackend
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer


class Handler(Core):
    """Provides read-only queries against the delegation graph.

    Reads state from the shared store to answer path, credit-limit,
    and buffer queries.
    """

    def __init__(
        self,
        name: str,
        bus: EventBus | LocalBus,
        store: StoreBackend,
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
        """Initialize the graph service query handlers."""
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
        self.handlers: dict[str, Any] = {
            Type.GRAPH_PATH: self.on_graph_path,
            Type.GRAPH_CREDIT_LIMIT: self.on_graph_credit_limit,
            Type.GRAPH_USERS: self.on_graph_users,
        }

    def handle(self, event: Message) -> None:
        """Process graph query events.

        Args:
            event: The incoming domain event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def on_graph_path(self, event: Message) -> None:
        """Compute the delegation path from a user to a seed.

        Args:
            event: The graph path query event.
        """
        user: str = event.payload.get("user", "")
        state: dict[str, Any] | None = self.safe_store_get("protocol:state")
        if state is None:
            logger.warning("graph path query for {}: protocol state not available", user)
            state = {}
        parent: dict[str, str] = state.get("parent", {})
        seeds: list[str] = state.get("seeds", [])
        path: list[str] = [user]
        current: str = user
        visited: set[str] = set()
        while current not in seeds:
            if current not in parent or current in visited:
                break
            visited.add(current)
            current = parent[current]
            path.append(current)
        path.reverse()
        self.emit(
            Type.GRAPH_PATH_RESULT,
            {
                "user": user,
                "path": path,
            },
            correlation_id=event.correlation_id,
        )

    def on_graph_credit_limit(self, event: Message) -> None:
        """Compute the available credit limit for a user.

        Args:
            event: The credit limit query event.
        """
        user: str = event.payload.get("user", "")
        state: dict[str, Any] | None = self.safe_store_get("protocol:state")
        if state is None:
            logger.warning("graph credit-limit query for {}: protocol state not available", user)
            state = {}
        earned: dict[str, Any] = state.get("earned", {})
        base_budget: dict[str, Any] = state.get("base_budget", {})
        parent: dict[str, str] = state.get("parent", {})
        delegation_raw: dict[str, Any] = state.get("delegation", {})
        children_raw: dict[str, list[str]] = state.get("children", {})
        seeds: list[str] = state.get("seeds", [])

        budget = to_money(base_budget.get(user, "0")) + to_money(earned.get(user, "0"))
        if user not in seeds and user in parent:
            sponsor: str = parent[user]
            edge_key: str = f"{sponsor}->{user}"
            budget = to_money(delegation_raw.get(edge_key, "0")) + to_money(earned.get(user, "0"))
        outgoing = sum(
            (to_money(delegation_raw.get(f"{user}->{child}", "0")) for child in children_raw.get(user, [])),
            to_money("0"),
        )
        self.emit(
            Type.GRAPH_CREDIT_LIMIT_RESULT,
            {
                "user": user,
                "credit_limit": float(budget - outgoing),
            },
            correlation_id=event.correlation_id,
        )

    def on_graph_users(self, event: Message) -> None:
        """Return the sorted list of all known users.

        Args:
            event: The graph users query event.
        """
        state: dict[str, Any] | None = self.safe_store_get("protocol:state")
        if state is None:
            state = {}
        earned: dict[str, float] = state.get("earned", {})
        self.emit(
            Type.GRAPH_USERS_RESULT,
            {"users": sorted(earned.keys())},
            correlation_id=event.correlation_id,
        )
