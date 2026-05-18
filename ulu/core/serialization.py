"""State serialization and persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ulu.core.models import STATE_SCHEMA_VERSION, ProtocolConfig, ProtocolState
from ulu.errors import ProtocolError


class SerializationMixin:
    """Methods for converting protocol state to/from persistent formats."""

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
    def from_state(cls, state: ProtocolState, config: ProtocolConfig | None = None):
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
    def from_dict(cls, payload: Mapping[str, Any]):
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
    def load_json(cls, path: str | Path):
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
