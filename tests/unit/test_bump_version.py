"""Tests for semantic versioning bump script.

Item 80 from production roadmap.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_script_path = Path(__file__).resolve().parents[2] / "scripts" / "bump_version.py"
_spec = importlib.util.spec_from_file_location("bump_version", _script_path)
_bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bump_version)


class TestBumpVersion:
    def test_bump_patch(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
        new = _bump_version.bump(toml, "patch")
        assert new == "1.2.4"
        assert 'version = "1.2.4"' in toml.read_text(encoding="utf-8")

    def test_bump_minor(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
        new = _bump_version.bump(toml, "minor")
        assert new == "1.3.0"

    def test_bump_major(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
        new = _bump_version.bump(toml, "major")
        assert new == "2.0.0"

    def test_bump_missing_version_raises(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text("[project]\n", encoding="utf-8")
        with pytest.raises(ValueError):
            _bump_version.bump(toml, "patch")
