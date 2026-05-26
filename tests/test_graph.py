"""Tests for GraphService — read-only delegation graph queries.

Tests verify behavior through emitted events only:
  - graph_path_result events
  - graph_credit_limit_result events
  - graph_users_result events
  - Edge cases: empty state, unknown users, missing fields
"""

from __future__ import annotations

from typing import Any

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event
from underwrite.__store__ import MemoryStore
from underwrite.services.graph.service import GraphService


def graph(store_data: dict[str, Any], bus=None) -> GraphService:
    store = MemoryStore()
    if store_data:
        store.set("protocol:state", store_data)
    return GraphService(service_id="graph", store=store, bus=bus)


class TestPathQuery:

    def test_path_from_leaf_to_seed(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_path_result", lambda e: received.append(e))
        svc = graph(
            {
                "parent": {
                    "alice": "bank",
                    "bob": "alice"
                },
                "seeds": ["bank"],
            },
            bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_path",
                  source="test",
                  payload={"user": "bob"}))
        assert received[0].payload["path"] == ["bank", "alice", "bob"]

    def test_path_for_seed_itself(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_path_result", lambda e: received.append(e))
        svc = graph({"parent": {}, "seeds": ["bank"]}, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_path",
                  source="test",
                  payload={"user": "bank"}))
        assert received[0].payload["path"] == ["bank"]

    def test_path_for_unknown_user_returns_singleton(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_path_result", lambda e: received.append(e))
        svc = graph({"parent": {}, "seeds": ["bank"]}, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_path",
                  source="test",
                  payload={"user": "ghost"}))
        assert received[0].payload["path"] == ["ghost"]

    def test_path_with_broken_chain(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_path_result", lambda e: received.append(e))
        svc = graph({
            "parent": {
                "alice": "bank"
            },
            "seeds": ["bank"],
        }, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_path",
                  source="test",
                  payload={"user": "orphan"}))
        assert received[0].payload["path"] == ["orphan"]

    def test_empty_state_path(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_path_result", lambda e: received.append(e))
        svc = graph({}, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_path", source="test",
                  payload={"user": "x"}))
        assert received[0].payload["path"] == ["x"]


class TestCreditLimitQuery:

    def test_credit_limit_for_seed(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_credit_limit_result", lambda e: received.append(e))
        svc = graph(
            {
                "seeds": ["bank"],
                "base_budget": {
                    "bank": 100000
                },
                "earned": {
                    "bank": 5000
                },
                "parent": {},
                "delegation": {},
                "children": {},
            },
            bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_credit_limit",
                  source="test",
                  payload={"user": "bank"}))
        assert received[0].payload["credit_limit"] == 105000.0

    def test_credit_limit_for_user(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_credit_limit_result", lambda e: received.append(e))
        svc = graph(
            {
                "seeds": ["bank"],
                "base_budget": {
                    "bank": 100000
                },
                "earned": {
                    "alice": 3000
                },
                "parent": {
                    "alice": "bank"
                },
                "delegation": {
                    "bank->alice": 50000
                },
                "children": {
                    "bank": ["alice"]
                },
            },
            bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_credit_limit",
                  source="test",
                  payload={"user": "alice"}))
        assert received[0].payload["credit_limit"] == 53000.0

    def test_credit_limit_with_outgoing_delegation(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_credit_limit_result", lambda e: received.append(e))
        svc = graph(
            {
                "seeds": ["bank"],
                "base_budget": {
                    "bank": 100000
                },
                "earned": {
                    "bank": 0
                },
                "parent": {},
                "delegation": {
                    "bank->alice": 30000
                },
                "children": {
                    "bank": ["alice"]
                },
            },
            bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_credit_limit",
                  source="test",
                  payload={"user": "bank"}))
        assert received[0].payload["credit_limit"] == 70000.0

    def test_empty_state_returns_zero(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_credit_limit_result", lambda e: received.append(e))
        svc = graph({}, bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="graph_credit_limit",
                  source="test",
                  payload={"user": "x"}))
        assert received[0].payload["credit_limit"] == 0.0


class TestUsersQuery:

    def test_returns_sorted_users(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_users_result", lambda e: received.append(e))
        svc = graph({"earned": {"bank": 0, "alice": 0, "bob": 0}}, bus=bus)
        bus.start()
        svc.handle(Event(event_type="graph_users", source="test", payload={}))
        assert received[0].payload["users"] == ["alice", "bank", "bob"]

    def test_empty_state_returns_empty_list(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe("graph_users_result", lambda e: received.append(e))
        svc = graph({}, bus=bus)
        bus.start()
        svc.handle(Event(event_type="graph_users", source="test", payload={}))
        assert received[0].payload["users"] == []


class TestEdgeCases:

    def test_ignores_unknown_event_type(self) -> None:
        svc = graph({})
        svc.handle(Event(event_type="unrelated", source="test", payload={}))
        assert svc.is_running is False

    def test_handles_none_store(self) -> None:
        svc = GraphService(service_id="graph", store=MemoryStore())
        svc.handle(Event(event_type="graph_users", source="test", payload={}))
        assert svc.is_running is False
