"""Tests for CLI error-handling paths — missing config, crypto guard, migrate."""

from __future__ import annotations

from underwrite.__cli__ import _load_config
from underwrite.__config__ import Configuration


class TestCLILoadConfig:

    def test_load_config_returns_default_when_no_file(self) -> None:
        config = _load_config()
        assert isinstance(config, Configuration)

    def test_load_config_default_has_no_services_enabled(self) -> None:
        config = _load_config()
        for _svc, cfg in config.services.items():
            assert cfg.enabled is False


class TestCLIIdentityEdgeCases:

    def test_identity_import_guard_does_not_crash(self) -> None:
        try:
            from underwrite.__identity__ import Identity
            ident = Identity.create("test-service")
            assert ident.service_id == "test-service"
        except ImportError:
            pass  # cryptography not installed — acceptable
