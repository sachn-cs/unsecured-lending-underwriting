"""underwrite — nano-service platform for delegated underwriting.

Each nano service is independently deployable (serverless / Modal) and
configuration-driven.  Start with:

    underwrite run mechanism
    underwrite run risk

Or use the full runtime:

    from underwrite.runtime import Runtime
    rt = Runtime()
    rt.start(["mechanism", "audit", "risk"])
    ...
    rt.stop()
"""

from underwrite.__bus__ import EventBus, LocalBus
from underwrite.__config__ import Configuration
from underwrite.__events__ import Event, EventType
from underwrite.__exceptions__ import (
    BusError,
    ConfigurationError,
    IdentityError,
    InfeasibleOperationError,
    InvariantViolationError,
    ProtocolError,
    ServiceNotFoundError,
    StoreError,
    UnderwriteError,
    UnknownUserError,
)
from underwrite.__identity__ import Identity
from underwrite.__runtime__ import Runtime
from underwrite.__store__ import FileStore, MemoryStore, Store
from underwrite.services import Core

try:
    from underwrite.__version__ import __version__ as _version
    from underwrite.__version__ import __version_tuple__ as _version_tuple
except ImportError:
    _version = "0.0.0"
    _version_tuple = (0, 0, 0)
__version__ = _version
__version_tuple__ = _version_tuple

__all__: list[str] = [
    "Runtime",
    "Configuration",
    "Core",
    "Event",
    "EventType",
    "Identity",
    "EventBus",
    "LocalBus",
    "Store",
    "MemoryStore",
    "FileStore",
    "UnderwriteError",
    "ConfigurationError",
    "ServiceNotFoundError",
    "IdentityError",
    "BusError",
    "StoreError",
    "ProtocolError",
    "UnknownUserError",
    "InvariantViolationError",
    "InfeasibleOperationError",
]
