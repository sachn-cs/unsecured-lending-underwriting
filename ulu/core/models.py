"""Core domain data classes for delegated underwriting."""

from __future__ import annotations

from dataclasses import dataclass

Edge = tuple[str, str]
STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LoanQuote:
    """Represents a priced loan quote at a fixed snapshot state."""

    borrower: str
    principal: float
    term: float
    default_probability: float
    protocol_rate: float
    protocol_premium: float
    delegation_utilization: float
    delegation_rate: float
    locked_by_edge: dict[Edge, float]
    delegation_payouts: dict[str, float]
    delegation_premium: float
    total_interest: float


@dataclass(frozen=True)
class ProtocolConfig:
    """Runtime checks configuration without semantic impact."""

    epsilon: float = 1e-12


@dataclass
class ProtocolState:
    """Serializable protocol state used for deterministic persistence."""

    seeds: list[str]
    parent: dict[str, str]
    children: dict[str, list[str]]
    delegation: dict[str, float]
    base_budget: dict[str, float]
    earned: dict[str, float]
    principal: dict[str, float]
