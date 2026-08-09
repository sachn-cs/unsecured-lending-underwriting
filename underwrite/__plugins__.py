"""Plugin discovery — loads third-party services via ``importlib.metadata.entry_points``.

Plugins register under the ``underwrite.services`` entry-point group.
Each entry point must resolve to a ``type[NanoService]``.

The default behaviour requires an explicit allowlist so that
arbitrary installed packages cannot register services with the
bus. Set the ``UNDERWRITE_PLUGINS`` environment variable to a
comma-separated list of plugin names to enable them, or set it to
``"*"`` to opt in to the legacy load-everything behaviour (NOT
recommended).

Example plugin ``pyproject.toml``::

    [project.entry-points."underwrite.services"]
    my_service = "my_package.module:MyService"

Then enable with ``UNDERWRITE_PLUGINS=my_service``.
"""

from __future__ import annotations

__all__ = [
    "PLUGIN_ALLOW_ALL",
    "PLUGIN_ENTRYPOINT_GROUP",
    "discover_plugins",
]

import importlib.metadata
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from underwrite.services import NanoService

from underwrite.__logger__ import logger

PLUGIN_ENTRYPOINT_GROUP: str = "underwrite.services"
PLUGIN_ALLOW_ALL: str = "*"

PLUGIN_ENV: str = "UNDERWRITE_PLUGINS"


def read_allowlist() -> frozenset[str] | None:
    """Reads the plugin allowlist from the environment.

    Returns:
        ``None`` to disable plugin loading, an empty frozenset to load
        no plugins, or a set of allowed plugin names. ``*`` is treated
        as "load everything" (legacy behaviour) and is not
        recommended.
    """
    raw = os.environ.get(PLUGIN_ENV)
    if raw is None:
        return frozenset()
    raw = raw.strip()
    if not raw:
        return frozenset()
    if raw == PLUGIN_ALLOW_ALL:
        logger.warning(
            "UNDERWRITE_PLUGINS={} — every installed 'underwrite.services' entry "
            "point will be loaded. This is a supply-chain risk; prefer an explicit allowlist.",
            PLUGIN_ALLOW_ALL,
        )
        return None
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


def discover_plugins() -> dict[str, type[NanoService]]:
    """Discover and load the allowlisted ``underwrite.services`` plugins.

    Returns:
        A dict mapping service name → NanoService subclass. Only
        plugins in the allowlist (set via ``UNDERWRITE_PLUGINS``) are
        loaded; any other installed entry points are ignored and a
        warning is logged for each.
    """
    allowlist = read_allowlist()

    plugins: dict[str, type[NanoService]] = {}
    for ep in importlib.metadata.entry_points(group=PLUGIN_ENTRYPOINT_GROUP):
        if allowlist is not None and ep.name not in allowlist:
            logger.warning(
                "ignoring plugin {} from {} — not in UNDERWRITE_PLUGINS allowlist",
                ep.name,
                ep.value,
            )
            continue
        try:
            cls = ep.load()
            plugins[ep.name] = cls
            logger.info("loaded plugin service {} from {}", ep.name, ep.value)
        except (ImportError, AttributeError, OSError):
            logger.exception("failed to load plugin {} ({})", ep.name, ep.value)
    return plugins
