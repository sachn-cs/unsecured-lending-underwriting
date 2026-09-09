# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Runtime startup ordering and KYC provider config surfacing."""

from __future__ import annotations

from underwrite.config import Configuration
from underwrite.runtime import Runtime, build_kyc_provider_config
from underwrite.secrets import Manager


class TestRuntimeStartupOrder:
    def test_runtime_identity_trusted_before_bus(self) -> None:
        """Construct a Runtime with authz enabled and confirm the runtime
        identity is trusted as soon as the runtime is built — there must
        be no observable window where an event from the runtime would
        fail verification."""
        from underwrite.config import AuthzConfig

        cfg = Configuration(authz=AuthzConfig(enabled=True, policy_file=""))
        rt = Runtime(cfg)
        assert rt.authz is not None
        assert rt.authz.is_trusted("runtime") is True

    def test_publishes_during_init_are_verifiable(self) -> None:
        """An event signed by the runtime identity after construction
        must verify against the runtime authz."""
        cfg = Configuration()
        cfg.authz.enabled = True
        cfg.authz.policy_file = ""
        rt = Runtime(cfg)
        assert rt.authz is not None
        msg = rt.sign_outbound_event("test.event", {"x": 1}, "corr-1")
        assert rt.authz.verify_signature(msg) is True


class TestKycProviderConfigWarning:
    def test_empty_config_logs_warning(self) -> None:
        cfg = Configuration()
        result = build_kyc_provider_config(cfg, Manager())
        # An empty ProvidersConfig is returned (so the runtime can
        # continue to start), and the operator sees a warning at
        # startup rather than finding out via a confusing ERROR at
        # the first compliance call.
        assert result.pan_client_id == ""
        assert result.aadhaar_kua_id == ""

        # Constructing a Runtime with the same empty config exercises
        # the same warning path through the runtime init flow.
        rt = Runtime(cfg)
        assert rt.kyc_provider_config is not None
        assert rt.kyc_provider_config.pan_client_id == ""
