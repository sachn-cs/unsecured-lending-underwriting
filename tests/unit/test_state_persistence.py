"""Unit tests for state persistence adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from ulu import DelegatedUnderwriting
from ulu.infra.state_persistence import StatePersistenceAdapter


class TestStatePersistenceAdapter:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        m = DelegatedUnderwriting()
        m.add_seed("s", 100.0)
        m.add_user("s", "a", 40.0)
        m.earned["a"] = 2.0
        m.principal["a"] = 5.0

        path = tmp_path / "state.json"
        StatePersistenceAdapter.save_json(m, path)
        restored = StatePersistenceAdapter.load_json(path, DelegatedUnderwriting)
        assert restored.to_dict() == m.to_dict()
        restored.assert_invariants()

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json")
        with pytest.raises(Exception, match="invalid JSON"):
            StatePersistenceAdapter.load_json(path, DelegatedUnderwriting)

    def test_load_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        with pytest.raises(Exception, match="failed to load"):
            StatePersistenceAdapter.load_json(path, DelegatedUnderwriting)
