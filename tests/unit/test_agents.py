"""Unit tests for recovery agent assignment."""

from __future__ import annotations

import pytest

from ulu.servicing.agents import RecoveryAgentService


class TestRecoveryAgentService:
    def test_register_and_get(self) -> None:
        svc = RecoveryAgentService()
        agent = svc.register_agent("a1", "Agent One")
        assert agent.agent_id == "a1"
        assert svc.get_agent("a1") == agent

    def test_assign_case(self) -> None:
        svc = RecoveryAgentService()
        svc.register_agent("a1", "Agent One")
        svc.assign_case("loan-1", "a1")
        assert svc.get_assignment("loan-1") == "a1"
        assert svc.get_agent("a1").assigned_cases == 1

    def test_close_case(self) -> None:
        svc = RecoveryAgentService()
        svc.register_agent("a1", "Agent One")
        svc.assign_case("loan-1", "a1")
        svc.close_case("loan-1", 5000.0)
        assert svc.get_agent("a1").closed_cases == 1
        assert svc.get_agent("a1").recovered_amount == 5000.0

    def test_close_unassigned_case(self) -> None:
        svc = RecoveryAgentService()
        with pytest.raises(ValueError, match="not assigned"):
            svc.close_case("loan-1", 1000.0)

    def test_assign_unknown_agent(self) -> None:
        svc = RecoveryAgentService()
        with pytest.raises(ValueError, match="unknown agent"):
            svc.assign_case("loan-1", "a1")

    def test_list_agents(self) -> None:
        svc = RecoveryAgentService()
        svc.register_agent("a1", "One")
        svc.register_agent("a2", "Two")
        assert len(svc.list_agents()) == 2
