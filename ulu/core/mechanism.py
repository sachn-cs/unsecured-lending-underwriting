"""Core delegated-underwriting mechanism and accounting state transitions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ulu.audit import AppendOnlyLedger
from ulu.errors import InfeasibleOperationError, InvariantViolationError, ProtocolError, UnknownUserError
from ulu.infra.logging import logger

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


class DelegatedUnderwriting:
    """Implements paper-defined mechanism transitions and pricing."""

    def __init__(
        self,
        config: ProtocolConfig | None = None,
        ledger: AppendOnlyLedger | None = None,
    ) -> None:
        """Initializes an empty protocol state."""
        self.config = config or ProtocolConfig()
        self.ledger = ledger

        self.seeds: set[str] = set()
        self.parent: dict[str, str] = {}
        self.children: dict[str, list[str]] = {}
        self.delegation: dict[Edge, float] = {}
        self.base_budget: dict[str, float] = {}
        self.earned: dict[str, float] = {}
        self.principal: dict[str, float] = {}

    def edge_key(self, sponsor: str, child: str) -> str:
        return f"{sponsor}->{child}"

    def edge_tuple(self, key: str) -> Edge:
        parts = key.split("->")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ProtocolError(f"invalid edge key: {key}")
        return (parts[0], parts[1])

    def require_user(self, user: str) -> None:
        if user not in self.earned:
            raise UnknownUserError(f"unknown user: {user}")

    def record_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.ledger is not None:
            self.ledger.append(event_type=event_type, payload=dict(payload))

    def validate_ancestry_paths(self, users: set[str]) -> None:
        """Validates acyclicity and parent reachability to seeds."""
        for user in users:
            seen: set[str] = set()
            current = user
            while current not in self.seeds:
                if current in seen:
                    raise InvariantViolationError(f"invalid state: cycle detected on ancestry path from {user}")
                seen.add(current)
                if current not in self.parent:
                    raise InvariantViolationError(f"invalid state: non-seed {current} has no parent")
                current = self.parent[current]

    def validate_structure(self) -> None:
        """Validates graph/state structural invariants."""
        if not self.seeds:
            raise InvariantViolationError("invalid state: at least one seed is required")

        users = set(self.earned)
        if set(self.principal) != users:
            raise InvariantViolationError("invalid state: principal keys mismatch earned keys")
        if set(self.children) != users:
            raise InvariantViolationError("invalid state: children keys mismatch earned keys")
        if not self.seeds.issubset(users):
            raise InvariantViolationError("invalid state: seeds must be known users")
        if set(self.base_budget) != self.seeds:
            raise InvariantViolationError("invalid state: base budgets must exist only for seeds")

        non_seeds = users - self.seeds
        if set(self.parent) != non_seeds:
            raise InvariantViolationError("invalid state: parent map must cover exactly non-seed users")

        for seed in self.seeds:
            if seed in self.parent:
                raise InvariantViolationError(f"invalid state: seed {seed} cannot have a parent")
            if self.base_budget[seed] <= 0:
                raise InvariantViolationError(f"invalid state: seed {seed} must have positive base budget")

        for user in non_seeds:
            parent = self.parent[user]
            if parent not in users:
                raise InvariantViolationError(f"invalid state: parent {parent} of {user} is unknown")
            if parent == user:
                raise InvariantViolationError(f"invalid state: self-parent cycle at {user}")

        self.validate_ancestry_paths(users)

    def add_seed(self, user: str, base_budget: float) -> None:
        """Adds a new seed account with positive base budget."""
        if user in self.earned:
            raise ProtocolError(f"user already exists: {user}")
        if base_budget <= 0:
            raise ProtocolError("seed base budget must be > 0")

        self.seeds.add(user)
        self.base_budget[user] = float(base_budget)
        self.earned[user] = 0.0
        self.principal[user] = 0.0
        self.children[user] = []

        logger.info("add_seed", user=user, base_budget=float(base_budget))
        self.record_event("add_seed", {"user": user, "base_budget": float(base_budget)})

    def add_user(self, sponsor: str, user: str, delegation_amount: float) -> None:
        """Adds a non-seed user sponsored with delegated capacity."""
        self.require_user(sponsor)
        if user in self.earned:
            raise ProtocolError(f"user already exists: {user}")
        if delegation_amount <= 0:
            raise ProtocolError("delegation must be > 0")
        if self.credit_limit(sponsor) < delegation_amount:
            raise InfeasibleOperationError("insufficient sponsor credit limit for delegation")

        self.parent[user] = sponsor
        self.children[user] = []
        self.children[sponsor].append(user)
        self.delegation[(sponsor, user)] = float(delegation_amount)
        self.earned[user] = 0.0
        self.principal[user] = 0.0

        logger.info(
            "add_user",
            sponsor=sponsor,
            user=user,
            delegation_amount=float(delegation_amount),
        )
        self.record_event(
            "add_user",
            {
                "sponsor": sponsor,
                "user": user,
                "delegation_amount": float(delegation_amount),
            },
        )

    def budget(self, user: str) -> float:
        """Returns current budget for a user."""
        self.require_user(user)
        if user in self.seeds:
            return self.base_budget[user] + self.earned[user]
        sponsor = self.parent[user]
        return self.delegation[(sponsor, user)] + self.earned[user]

    def outgoing_delegation(self, user: str) -> float:
        """Returns total outgoing delegation from a user."""
        self.require_user(user)
        return sum(self.delegation[(user, child)] for child in self.children[user])

    def credit_limit(self, user: str) -> float:
        """Returns paper-defined credit limit c_u."""
        return self.budget(user) - self.outgoing_delegation(user)

    def total_credit_limit(self) -> float:
        """Returns aggregate credit limit across all users."""
        return sum(self.credit_limit(user) for user in self.earned)

    def required_delegation(self, user: str) -> float:
        """Computes required delegation R_v recursively for non-seeds."""
        self.require_user(user)
        if user in self.seeds:
            raise ProtocolError("required delegation is defined only for non-seeds")
        child_requirement = sum(self.required_delegation(child) for child in self.children[user])
        return max(0.0, self.principal[user] + child_requirement - self.earned[user])

    def revoke(self, sponsor: str, child: str, new_delegation: float) -> None:
        """Sets edge delegation amount if revocation remains solvent."""
        self.require_user(sponsor)
        self.require_user(child)
        edge = (sponsor, child)
        if edge not in self.delegation:
            raise ProtocolError("unknown delegation edge")
        if self.parent.get(child) != sponsor:
            raise ProtocolError("not the parent-child edge")
        if new_delegation < 0:
            raise ProtocolError("new delegation must be >= 0")

        needed = self.required_delegation(child)
        if new_delegation < needed:
            raise InfeasibleOperationError("revocation would make subtree insolvent")

        old_delegation = self.delegation[edge]
        if new_delegation > old_delegation:
            delta = new_delegation - old_delegation
            if self.credit_limit(sponsor) < delta:
                raise InfeasibleOperationError("insufficient credit limit to increase delegation")

        self.delegation[edge] = float(new_delegation)
        logger.info(
            "revoke",
            sponsor=sponsor,
            child=child,
            old_delegation=float(old_delegation),
            new_delegation=float(new_delegation),
        )
        self.record_event(
            "revoke",
            {
                "sponsor": sponsor,
                "child": child,
                "old_delegation": float(old_delegation),
                "new_delegation": float(new_delegation),
            },
        )

    def repay(self, user: str, delta_earned: float) -> None:
        """Applies earned-credit increment from repayment."""
        self.require_user(user)
        if delta_earned < 0:
            raise ProtocolError("delta earned must be >= 0")
        self.earned[user] += float(delta_earned)

        logger.info("repay", user=user, delta_earned=float(delta_earned))
        self.record_event("repay", {"user": user, "delta_earned": float(delta_earned)})

    def path_seed_to(self, user: str) -> list[str]:
        """Returns the unique seed-to-user sponsor path."""
        self.require_user(user)
        reverse_path = [user]
        current = user
        seen = {user}
        while current not in self.seeds:
            if current not in self.parent:
                raise InvariantViolationError(f"invalid state: non-seed {current} has no parent")
            current = self.parent[current]
            if current in seen:
                raise InvariantViolationError(f"invalid state: cycle detected while walking path for {user}")
            seen.add(current)
            reverse_path.append(current)
        return list(reversed(reverse_path))

    def local_buffer(self, user: str) -> float:
        """Computes local buffer b_u for a path node."""
        self.require_user(user)
        child_requirements = sum(self.required_delegation(child) for child in self.children[user])
        return max(0.0, self.earned[user] - self.principal[user] - child_requirements)

    def downstream_buffers(self, borrower: str) -> dict[Edge, float]:
        """Computes downstream buffers B_k for each edge on path to borrower."""
        path = self.path_seed_to(borrower)
        local_by_node = {node: self.local_buffer(node) for node in path}
        downstream: dict[Edge, float] = {}

        for index in range(len(path) - 1):
            below = sum(local_by_node[path[i]] for i in range(index + 1, len(path)))
            downstream[(path[index], path[index + 1])] = below

        return downstream

    def locked_delegation(self, borrower: str, principal: float) -> dict[Edge, float]:
        """Computes locked delegation m_k and checks path feasibility."""
        if principal <= 0:
            raise ProtocolError("principal must be > 0")

        buffers = self.downstream_buffers(borrower)
        locked: dict[Edge, float] = {}
        for edge, buffer_value in buffers.items():
            required = max(0.0, principal - buffer_value)
            if required > self.delegation[edge]:
                raise InfeasibleOperationError("loan infeasible on sponsor path")
            locked[edge] = required
        return locked

    def seed_delegation_utilization(self) -> float:
        """Returns U^D for current state."""
        denominator = sum(self.budget(seed) for seed in self.seeds)
        if denominator <= 0:
            raise InvariantViolationError("invalid state: non-positive seed budget total")

        numerator = 0.0
        for seed in self.seeds:
            for child in self.children[seed]:
                numerator += self.delegation[(seed, child)]

        utilization = numerator / denominator
        epsilon = self.config.epsilon
        if utilization < -epsilon or utilization > 1 + epsilon:
            raise InvariantViolationError("invalid state: utilization out of [0,1]")
        return min(max(utilization, 0.0), 1.0)

    def protocol_break_even_rate(self, default_probability: float, term: float) -> float:
        """Returns exact break-even protocol rate from theorem condition."""
        if not (0.0 < default_probability < 1.0):
            raise ProtocolError("default probability must be in (0,1)")
        if term <= 0:
            raise ProtocolError("term must be > 0")
        _EPS = 1e-12
        _MAX_RATE = 1e6
        clamped_dp = max(default_probability, _EPS)
        clamped_term = max(term, _EPS)
        rate = clamped_dp / ((1 - clamped_dp) * clamped_term)
        return min(rate, _MAX_RATE)

    def validate_quote_inputs(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> None:
        self.require_user(borrower)
        if self.principal[borrower] != 0:
            raise InfeasibleOperationError("borrower already has outstanding principal")
        if self.credit_limit(borrower) < principal:
            raise InfeasibleOperationError("borrower principal exceeds credit limit")
        if term <= 0 or principal <= 0:
            raise ProtocolError("principal and term must be > 0")
        if protocol_rate < 0 or max_delegation_rate < 0:
            raise ProtocolError("rates must be >= 0")
        if not (0.0 < default_probability < 1.0):
            raise ProtocolError("default probability must be in (0,1)")

    def quote_loan(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> LoanQuote:
        """Produces a snapshot loan quote without mutating principal."""
        self.validate_quote_inputs(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            max_delegation_rate=max_delegation_rate,
        )

        protocol_premium = protocol_rate * principal * term
        utilization = self.seed_delegation_utilization()
        delegation_rate = max_delegation_rate * (1 - utilization)
        locked = self.locked_delegation(borrower, principal)

        path = self.path_seed_to(borrower)
        payouts: dict[str, float] = {}
        for index in range(len(path) - 1):
            sponsor = path[index]
            edge = (path[index], path[index + 1])
            payouts[sponsor] = delegation_rate * locked[edge] * term

        delegation_premium = sum(payouts.values())
        return LoanQuote(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            protocol_premium=protocol_premium,
            delegation_utilization=utilization,
            delegation_rate=delegation_rate,
            locked_by_edge=locked,
            delegation_payouts=payouts,
            delegation_premium=delegation_premium,
            total_interest=protocol_premium + delegation_premium,
        )

    def quote_loan_with_estimated_default(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability_estimator: Any,
        feature_row: Any,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> LoanQuote:
        """Quotes a loan using externally estimated default probability."""
        probabilities = default_probability_estimator.predict_default_probability(feature_row)
        default_probability = float(probabilities[0])
        return self.quote_loan(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            max_delegation_rate=max_delegation_rate,
        )

    def originate_loan(
        self,
        borrower: str,
        principal: float,
        term: float,
        default_probability: float,
        protocol_rate: float,
        max_delegation_rate: float,
    ) -> LoanQuote:
        """Quotes and originates a loan by setting borrower principal."""
        quote = self.quote_loan(
            borrower=borrower,
            principal=principal,
            term=term,
            default_probability=default_probability,
            protocol_rate=protocol_rate,
            max_delegation_rate=max_delegation_rate,
        )
        self.principal[borrower] = principal

        logger.info(
            "originate_loan",
            borrower=borrower,
            principal=float(principal),
            term=float(term),
        )
        self.record_event(
            "originate_loan",
            {"borrower": borrower, "principal": float(principal), "term": float(term)},
        )
        return quote

    def default(self, borrower: str) -> None:
        """Applies default loss propagation on borrower sponsor path."""
        self.require_user(borrower)
        borrower_principal = self.principal[borrower]
        if borrower_principal <= 0:
            raise InfeasibleOperationError("borrower has no outstanding principal")

        absorb_borrower = min(self.earned[borrower], borrower_principal)
        self.earned[borrower] -= absorb_borrower
        loss = borrower_principal - absorb_borrower

        current = borrower
        while loss > 0 and current not in self.seeds:
            sponsor = self.parent[current]
            edge = (sponsor, current)
            absorb_sponsor = min(self.earned[sponsor], loss)
            self.earned[sponsor] -= absorb_sponsor
            loss -= absorb_sponsor
            if loss > 0:
                if self.delegation[edge] < loss:
                    raise InvariantViolationError("invalid state: insufficient delegation for default propagation")
                self.delegation[edge] -= loss
            current = sponsor

        if loss > 0:
            if current not in self.seeds:
                raise InvariantViolationError("invalid state: residual loss did not reach seed")
            seed = current
            if self.base_budget[seed] < loss:
                raise InvariantViolationError("invalid state: seed base budget overdraft")
            self.base_budget[seed] -= loss

        self.principal[borrower] = 0.0
        logger.info("default", borrower=borrower, principal=float(borrower_principal))
        self.record_event("default", {"borrower": borrower, "principal": float(borrower_principal)})

    def assert_invariants(self) -> None:
        """Raises if accounting or structure invariants are violated."""
        self.validate_structure()

        epsilon = self.config.epsilon
        for user in self.earned:
            if self.earned[user] < -epsilon:
                raise InvariantViolationError(f"negative earned credit for {user}")
            if self.principal[user] < -epsilon:
                raise InvariantViolationError(f"negative principal for {user}")
            if self.credit_limit(user) < -epsilon:
                raise InvariantViolationError(f"negative credit limit for {user}")

        for (sponsor, child), amount in self.delegation.items():
            if amount < -epsilon:
                raise InvariantViolationError(f"negative delegation on edge {sponsor}->{child}")
            if self.parent.get(child) != sponsor:
                raise InvariantViolationError(f"mismatched parent for edge {sponsor}->{child}")
            if child not in self.children.get(sponsor, []):
                raise InvariantViolationError(f"missing child link for edge {sponsor}->{child}")

    def to_state(self) -> ProtocolState:
        """Converts current in-memory state to serializable ProtocolState."""
        delegation = {self.edge_key(sponsor, child): amount for (sponsor, child), amount in self.delegation.items()}
        children = {user: list(child_list) for user, child_list in self.children.items()}
        return ProtocolState(
            seeds=sorted(self.seeds),
            parent=dict(self.parent),
            children=children,
            delegation=delegation,
            base_budget=dict(self.base_budget),
            earned=dict(self.earned),
            principal=dict(self.principal),
        )

    @classmethod
    def from_state(cls, state: ProtocolState, config: ProtocolConfig | None = None) -> DelegatedUnderwriting:
        """Builds a mechanism instance from a ProtocolState."""
        instance = cls(config=config)
        instance.seeds = set(state.seeds)
        instance.parent = dict(state.parent)
        instance.children = {user: list(child_list) for user, child_list in state.children.items()}
        instance.delegation = {instance.edge_tuple(key): float(value) for key, value in state.delegation.items()}
        instance.base_budget = {user: float(value) for user, value in state.base_budget.items()}
        instance.earned = {user: float(value) for user, value in state.earned.items()}
        instance.principal = {user: float(value) for user, value in state.principal.items()}
        instance.assert_invariants()
        return instance

    def to_dict(self) -> dict[str, Any]:
        """Serializes protocol config and state to a dictionary."""
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "config": {"epsilon": self.config.epsilon},
            "state": self.to_state().__dict__,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DelegatedUnderwriting:
        """Deserializes an instance from a dictionary payload."""
        if "state" not in payload:
            raise ProtocolError("missing state payload")

        schema_version = payload.get("schema_version")
        if schema_version != STATE_SCHEMA_VERSION:
            raise ProtocolError(f"unsupported schema_version: {schema_version}, expected {STATE_SCHEMA_VERSION}")

        config_data = payload.get("config", {})
        config = ProtocolConfig(epsilon=float(config_data.get("epsilon", 1e-12)))
        state_data = payload["state"]
        required_keys = ("seeds", "parent", "children", "delegation", "base_budget", "earned", "principal")
        missing = [k for k in required_keys if k not in state_data]
        if missing:
            raise ProtocolError(f"missing state keys: {missing}")
        state = ProtocolState(
            seeds=list(state_data["seeds"]),
            parent=dict(state_data["parent"]),
            children={user: list(child_list) for user, child_list in state_data["children"].items()},
            delegation={key: float(value) for key, value in state_data["delegation"].items()},
            base_budget={user: float(value) for user, value in state_data["base_budget"].items()},
            earned={user: float(value) for user, value in state_data["earned"].items()},
            principal={user: float(value) for user, value in state_data["principal"].items()},
        )
        return cls.from_state(state, config=config)

    def save_json(self, path: str | Path) -> None:
        """Writes state payload to a JSON file."""
        target = Path(path)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        try:
            target.write_text(payload, encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(f"failed to save state to {target}: {exc}") from exc

    @classmethod
    def load_json(cls, path: str | Path) -> DelegatedUnderwriting:
        """Loads a mechanism instance from JSON state file."""
        target = Path(path)
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(f"failed to load state from {target}: {exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"invalid JSON in state file {target}: {exc}") from exc
        return cls.from_dict(payload)
