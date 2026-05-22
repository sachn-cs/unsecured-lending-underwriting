"""Delegation graph queries — read-only access to protocol state."""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event
from underwrite.services import NanoService


class GraphService(NanoService):
    """Provides read-only queries against the delegation graph.

    Reads state from the shared store to answer path, credit-limit,
    and buffer queries.
    """

    def handle(self, event: Event) -> None:
        if event.event_type == "graph_path":
            self.__query_path(event)
        elif event.event_type == "graph_credit_limit":
            self.__query_credit_limit(event)
        elif event.event_type == "graph_users":
            self.__query_users(event)

    def __query_path(self, event: Event) -> None:
        user: str = event.payload.get("user", "")
        state: dict[str, Any] = self.store.get("protocol:state") or {}
        parent: dict[str, str] = state.get("parent", {})
        seeds: list[str] = state.get("seeds", [])
        path: list[str] = [user]
        current: str = user
        while current not in seeds:
            if current not in parent:
                break
            current = parent[current]
            path.append(current)
        path.reverse()
        self.emit("graph_path_result", {
            "user": user,
            "path": path
        },
                  correlation_id=event.correlation_id)

    def __query_credit_limit(self, event: Event) -> None:
        user: str = event.payload.get("user", "")
        state: dict[str, Any] = self.store.get("protocol:state") or {}
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
        outgoing: float = sum(
            delegation_raw.get(f"{user}->{child}", 0.0)
            for child in children_raw.get(user, []))
        self.emit("graph_credit_limit_result", {
            "user": user,
            "credit_limit": budget - outgoing,
        },
                  correlation_id=event.correlation_id)

    def __query_users(self, event: Event) -> None:
        state: dict[str, Any] = self.store.get("protocol:state") or {}
        earned: dict[str, float] = state.get("earned", {})
        self.emit("graph_users_result", {"users": sorted(earned.keys())},
                  correlation_id=event.correlation_id)
