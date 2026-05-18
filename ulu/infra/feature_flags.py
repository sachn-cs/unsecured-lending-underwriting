"""Feature flag service for toggling functionality without deployment.

Item 81 from production roadmap.
"""

from __future__ import annotations

import os
from typing import Any

from ulu.infra.logging import logger


class FeatureFlagService:
    """In-memory feature flag store with environment override support.

    Production should use LaunchDarkly, Unleash, or Redis backend.
    """

    def __init__(self, overrides: dict[str, bool] | None = None) -> None:
        self._flags: dict[str, bool] = dict(overrides or {})

    def register(self, name: str, default: bool = False) -> None:
        """Registers a flag with a default value."""
        env_val = os.environ.get(f"FF_{name.upper()}")
        if env_val is not None:
            value = env_val.lower() in {"1", "true", "yes", "on"}
            self._flags[name] = value
            logger.info("feature_flag_env_override", name=name, value=value)
        elif name not in self._flags:
            self._flags[name] = default
            logger.info("feature_flag_registered", name=name, default=default)

    def is_enabled(self, name: str) -> bool:
        """Returns current state of a flag."""
        return self._flags.get(name, False)

    def enable(self, name: str) -> None:
        """Enables a flag at runtime."""
        self._flags[name] = True
        logger.info("feature_flag_enabled", name=name)

    def disable(self, name: str) -> None:
        """Disables a flag at runtime."""
        self._flags[name] = False
        logger.info("feature_flag_disabled", name=name)

    def state(self) -> dict[str, bool]:
        """Returns snapshot of all flags."""
        return dict(self._flags)

    def check(
        self,
        name: str,
        *,
        on_enabled: Any | None = None,
        on_disabled: Any | None = None,
    ) -> Any | None:
        """Returns on_enabled if flag is on, otherwise on_disabled."""
        return on_enabled if self.is_enabled(name) else on_disabled
