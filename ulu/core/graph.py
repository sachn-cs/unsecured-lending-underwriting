"""Graph traversal and structural validation mixin."""

from __future__ import annotations

from ulu.core.models import Edge
from ulu.errors import InfeasibleOperationError, InvariantViolationError, ProtocolError, UnknownUserError


class GraphMixin:
    """Methods for delegation graph structure and ancestry validation."""

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
