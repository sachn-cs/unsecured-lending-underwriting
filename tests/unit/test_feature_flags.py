"""Unit tests for feature flag service."""

from __future__ import annotations

from ulu.infra.feature_flags import FeatureFlagService


class TestFeatureFlagService:
    def test_is_enabled_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_FEATURE_TEST_FLAG", "true")
        svc = FeatureFlagService()
        assert svc.is_enabled("test_flag") is True

    def test_is_disabled_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_FEATURE_TEST_FLAG", "false")
        svc = FeatureFlagService()
        assert svc.is_enabled("test_flag") is False

    def test_is_enabled_from_override(self) -> None:
        svc = FeatureFlagService(overrides={"my_feature": True})
        assert svc.is_enabled("my_feature") is True

    def test_enable_disable_runtime(self) -> None:
        svc = FeatureFlagService()
        svc.enable("runtime_feature")
        assert svc.is_enabled("runtime_feature") is True
        svc.disable("runtime_feature")
        assert svc.is_enabled("runtime_feature") is False

    def test_list_flags(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_FEATURE_ALPHA", "true")
        monkeypatch.setenv("ULU_FEATURE_BETA", "false")
        svc = FeatureFlagService()
        flags = svc.list_flags()
        names = {f.name for f in flags}
        assert "alpha" in names
        assert "beta" in names

    def test_clear_cache(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_FEATURE_CACHED", "true")
        svc = FeatureFlagService()
        assert svc.is_enabled("cached") is True
        monkeypatch.setenv("ULU_FEATURE_CACHED", "false")
        svc.clear_cache()
        assert svc.is_enabled("cached") is False
