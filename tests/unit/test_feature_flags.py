"""Unit tests for feature flag service."""

from __future__ import annotations

from ulu.infra.feature_flags import FeatureFlagService


class TestFeatureFlagService:
    def test_register_default_false(self) -> None:
        svc = FeatureFlagService()
        svc.register("new_ui", default=False)
        assert svc.is_enabled("new_ui") is False

    def test_register_default_true(self) -> None:
        svc = FeatureFlagService()
        svc.register("new_ui", default=True)
        assert svc.is_enabled("new_ui") is True

    def test_enable_disable(self) -> None:
        svc = FeatureFlagService()
        svc.register("beta")
        svc.enable("beta")
        assert svc.is_enabled("beta") is True
        svc.disable("beta")
        assert svc.is_enabled("beta") is False

    def test_env_override_true(self, monkeypatch) -> None:
        monkeypatch.setenv("FF_BETA", "true")
        svc = FeatureFlagService()
        svc.register("beta", default=False)
        assert svc.is_enabled("beta") is True

    def test_env_override_false(self, monkeypatch) -> None:
        monkeypatch.setenv("FF_BETA", "0")
        svc = FeatureFlagService()
        svc.register("beta", default=True)
        assert svc.is_enabled("beta") is False

    def test_state_snapshot(self) -> None:
        svc = FeatureFlagService(overrides={"a": True, "b": False})
        assert svc.state() == {"a": True, "b": False}

    def test_check(self) -> None:
        svc = FeatureFlagService(overrides={"dark_mode": True})
        assert svc.check("dark_mode", on_enabled="yes", on_disabled="no") == "yes"
        assert svc.check("missing", on_enabled="yes", on_disabled="no") == "no"
