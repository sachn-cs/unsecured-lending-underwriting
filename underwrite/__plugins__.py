"""Plugin discovery — loads third-party services via ``importlib.metadata.entry_points``.

Plugins register under the ``underwrite.services`` entry-point group.
Each entry point must resolve to a callable that returns a
``type[NanoService]`` (or a ``NanoService`` subclass).

Example plugin ``pyproject.toml``::

    [project.entry-points."underwrite.services"]
    my_service = "my_package.module:MyService"

The service is discovered, loaded, and registered at runtime by
``discover_plugins()``.
"""

from __future__ import annotations

__all__ = [
    "discover_plugins",
    "PLUGIN_ENTRYPOINT_GROUP",
]

import importlib.metadata
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from underwrite.services import NanoService

logger = logging.getLogger(__name__)

PLUGIN_ENTRYPOINT_GROUP: str = "underwrite.services"


def discover_plugins() -> dict[str, type[NanoService]]:
    """Discover and load all registered ``underwrite.services`` plugins.

    Returns:
        A dict mapping service name → NanoService subclass.
    """
    plugins: dict[str, type[NanoService]] = {}
    for ep in importlib.metadata.entry_points(group=PLUGIN_ENTRYPOINT_GROUP):
        try:
            cls = ep.load()
            plugins[ep.name] = cls
            logger.info("loaded plugin service %s from %s", ep.name, ep.value)
        except Exception:
            logger.exception("failed to load plugin %s (%s)", ep.name, ep.value)
    return plugins
