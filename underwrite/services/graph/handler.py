"""Delegation graph queries - read-only access to protocol state."""

from __future__ import annotations

from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus
from underwrite.__events__ import Event, EventType
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__logger__ import logger
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.services.base import Core


class GraphHandler(Core):
    """Provides read-only queries against the delegation graph.

    Reads state from the shared store to answer path, credit-limit,
    and buffer queries.
    """

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Identity | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the graph service query handlers."""
        super().__init__(
            service_id=service_id,
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
        self.handlers: dict[str, Any] = {
            EventType.GRAPH_PATH: self.__on_graph_path,
            EventType.GRAPH_CREDIT_LIMIT: self.__on_graph_credit_limit,
            EventType.GRAPH_USERS: self.__on_graph_users,
        }

    def handle(self, event: Event) -> None:
        """Process graph query events.

        Args:
            event: The incoming domain event.
        """
        handler = self.handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def __on_graph_path(self, event: Event) -> None:
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
            EventType.GRAPH_PATH_RESULT,
            {
                "user": user,
                "path": path,
            },
            correlation_id=event.correlation_id,
        )

    def __on_graph_credit_limit(self, event: Event) -> None:
        """Compute the available credit limit for a user.

        Args:
            event: The credit limit query event.
        """
        user: str = event.payload.get("user", "")
        state: dict[str, Any] | None = self.safe_store_get("protocol:state")
        if state is None:
            logger.warning("graph credit-limit query for {}: protocol state not available", user)
            state = {}
        earned: dict[str, float] = state.get("earned", {})
        base_budget: dict[str, float] = state.get("base_budget", {})
        parent: dict[str, str] = state.get("parent", {})
        delegation_raw: dict[str, float] = state.get("delegation", {})
        children_raw: dict[str, list[str]] = state.get("children", {})
        seeds: list[str] = state.get("seeds", [])

        budget: float = base_budget.get(user, 0.0) + earned.get(user, 0.0)
        if user not in seeds and user in parent:
            sponsor: str = parent[user]
            edge_key: str = f"{sponsor}->{user}"
            budget = delegation_raw.get(edge_key, 0.0) + earned.get(user, 0.0)
        outgoing: float = sum(delegation_raw.get(f"{user}->{child}", 0.0) for child in children_raw.get(user, []))
        self.emit(
            EventType.GRAPH_CREDIT_LIMIT_RESULT,
            {
                "user": user,
                "credit_limit": budget - outgoing,
            },
            correlation_id=event.correlation_id,
        )

    def __on_graph_users(self, event: Event) -> None:
        """Return the sorted list of all known users.

        Args:
            event: The graph users query event.
        """
        state: dict[str, Any] | None = self.safe_store_get("protocol:state")
        if state is None:
            state = {}
        earned: dict[str, float] = state.get("earned", {})
        self.emit(
            EventType.GRAPH_USERS_RESULT,
            {"users": sorted(earned.keys())},
            correlation_id=event.correlation_id,
        )
