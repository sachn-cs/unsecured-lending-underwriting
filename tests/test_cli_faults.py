"""Tests for CLI error-handling paths — missing config, crypto guard, migrate."""

from __future__ import annotations

import pytest

from underwrite.cli import load_config
from underwrite.config import Configuration


class TestCLILoadConfig:
    def test_load_config_returns_default_when_no_file(self) -> None:
        config = load_config()
        assert isinstance(config, Configuration)

    def test_load_config_default_has_no_services_enabled(self) -> None:
        config = load_config()
        for _name, cfg in config.services.items():
            assert cfg.enabled is False


class TestCLIIdentityEdgeCases:
    def test_identity_import_guard_does_not_crash(self) -> None:
        try:
            from underwrite.keypair import Keypair
        except ImportError:
            pytest.skip("cryptography not installed")
        ident = Keypair.create("test-service")
        assert ident.name == "test-service"
