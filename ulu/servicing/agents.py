"""Recovery agent assignment and performance tracking.

Item 34 from production roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass

from ulu.infra.logging import logger


@dataclass
class RecoveryAgent:
    """Represents a field recovery agent."""

    agent_id: str
    name: str
    assigned_cases: int = 0
    closed_cases: int = 0
    recovered_amount: float = 0.0
    performance_score: float = 0.0


class RecoveryAgentService:
    """Tracks recovery agents and assigns defaulted loans."""

    def __init__(self) -> None:
        self._agents: dict[str, RecoveryAgent] = {}
        self._assignments: dict[str, str] = {}

    def register_agent(self, agent_id: str, name: str) -> RecoveryAgent:
        """Registers a new recovery agent."""
        agent = RecoveryAgent(agent_id=agent_id, name=name)
        self._agents[agent_id] = agent
        logger.info("recovery_agent_registered", agent_id=agent_id, name=name)
        return agent

    def assign_case(self, loan_id: str, agent_id: str) -> bool:
        """Assigns a loan to a recovery agent."""
        if agent_id not in self._agents:
            raise ValueError(f"unknown agent: {agent_id}")
        self._agents[agent_id].assigned_cases += 1
        self._assignments[loan_id] = agent_id
        logger.info("recovery_case_assigned", loan_id=loan_id, agent_id=agent_id)
        return True

    def close_case(self, loan_id: str, recovered: float) -> None:
        """Marks a case as closed and updates agent metrics."""
        agent_id = self._assignments.get(loan_id)
        if agent_id is None:
            raise ValueError(f"loan {loan_id} not assigned to any agent")
        agent = self._agents[agent_id]
        agent.closed_cases += 1
        agent.recovered_amount += recovered
        if agent.assigned_cases > 0:
            agent.performance_score = agent.closed_cases / agent.assigned_cases
        logger.info("recovery_case_closed", loan_id=loan_id, agent_id=agent_id, recovered=recovered)

    def get_agent(self, agent_id: str) -> RecoveryAgent | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[RecoveryAgent]:
        return list(self._agents.values())

    def get_assignment(self, loan_id: str) -> str | None:
        return self._assignments.get(loan_id)
