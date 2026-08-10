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

from underwrite.bus import EventBus
from underwrite.config import Configuration
from underwrite.exceptions import (
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
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.runtime import Runtime
from underwrite.services import Core
from underwrite.store import Disk, InMemory, Store

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
    "Message",
    "Type",
    "Keypair",
    "EventBus",
    "LocalBus",
    "Store",
    "InMemory",
    "Disk",
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
