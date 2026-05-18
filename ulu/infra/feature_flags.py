"""Simple environment-based feature flag service.

Items 81 and 112 from production roadmap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class FeatureFlag:
    """Represents a single feature flag with metadata."""

    name: str
    enabled: bool
    description: str = ""


class FeatureFlagService:
    """Manages feature flags from environment variables.

    Flags are read from env vars prefixed with ULU_FEATURE_.
    Example: ULU_FEATURE_NEW_UI=true enables the "new_ui" flag.
    """

    PREFIX = "ULU_FEATURE_"

    def __init__(self, overrides: dict[str, bool] | None = None) -> None:
        self._overrides = overrides or {}
        self._cache: dict[str, bool] = {}

    def is_enabled(self, name: str) -> bool:
        """Returns True if the named feature flag is enabled."""
        if name in self._overrides:
            return self._overrides[name]
        if name not in self._cache:
            env_key = f"{self.PREFIX}{name.upper()}"
            self._cache[name] = os.environ.get(env_key, "").lower() in ("true", "1", "yes", "on")
        return self._cache[name]

    def enable(self, name: str) -> None:
        """Enables a flag at runtime (in-memory only)."""
        self._overrides[name] = True

    def disable(self, name: str) -> None:
        """Disables a flag at runtime (in-memory only)."""
        self._overrides[name] = False

    def list_flags(self) -> list[FeatureFlag]:
        """Returns all known feature flags from environment."""
        flags: list[FeatureFlag] = []
        for key, value in os.environ.items():
            if key.startswith(self.PREFIX):
                name = key[len(self.PREFIX) :].lower()
                enabled = value.lower() in ("true", "1", "yes", "on")
                flags.append(FeatureFlag(name=name, enabled=enabled))
        for name, enabled in self._overrides.items():
            if not any(f.name == name for f in flags):
                flags.append(FeatureFlag(name=name, enabled=enabled))
        return sorted(flags, key=lambda f: f.name)

    def clear_cache(self) -> None:
        """Clears the env-var cache (useful in tests)."""
        self._cache.clear()
