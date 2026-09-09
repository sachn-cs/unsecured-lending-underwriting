# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for runtime.build_authz default policy behavior."""

from __future__ import annotations

import json
from pathlib import Path

from underwrite.config import AuthzConfig, Configuration
from underwrite.runtime import build_authz


def _acl_with(authz: AuthzConfig):
    cfg = Configuration(authz=authz)
    return build_authz(cfg.authz)


class TestBuildAuthzDefaultPolicy:
    def test_default_deny_when_no_policy_file(self) -> None:
        """Authz enabled without a policy file must default to deny."""
        acl = _acl_with(AuthzConfig(enabled=True, policy_file=""))
        assert acl is not None
        assert acl.check_publish("anyone", "anything") is False
        assert acl.check_subscribe("anyone", "anything") is False

    def test_default_allow_opt_in(self) -> None:
        """Operators can opt back into permissive default for backward compat."""
        acl = _acl_with(
            AuthzConfig(enabled=True, policy_file="", default_allow_when_no_policy=True),
        )
        assert acl is not None
        assert acl.check_publish("anyone", "anything") is True

    def test_disabled_returns_none(self) -> None:
        """Authz explicitly disabled returns None — caller skips checks."""
        assert _acl_with(AuthzConfig(enabled=False)) is None

    def test_policy_file_overrides_default(self, tmp_path: Path) -> None:
        """When a policy file is provided, its rules are applied."""
        policy = tmp_path / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "allow": [{"subject": "risk", "resource": "publish:*"}],
                    "deny": [{"subject": "fraud", "resource": "publish:*"}],
                },
            ),
        )
        acl = _acl_with(
            AuthzConfig(enabled=True, policy_file=str(policy)),
        )
        assert acl is not None
        assert acl.check_publish("risk", "loan.originated") is True
        assert acl.check_publish("fraud", "loan.originated") is False
        assert acl.check_publish("anyone", "loan.originated") is False

    def test_missing_policy_file_logs_and_denies(self, tmp_path: Path) -> None:
        """A configured-but-missing policy file falls back to default-deny."""
        missing = tmp_path / "nope.json"
        acl = _acl_with(AuthzConfig(enabled=True, policy_file=str(missing)))
        assert acl is not None
        assert acl.check_publish("anyone", "anything") is False
