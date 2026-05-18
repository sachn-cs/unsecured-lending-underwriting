"""Protocol exception hierarchy."""


class ProtocolError(ValueError):
    """Base exception for protocol-level invalid operations."""


class UnknownUserError(ProtocolError):
    """Raised when referring to an unknown user identifier."""


class InvariantViolationError(ProtocolError):
    """Raised when the internal accounting state is inconsistent."""


class InfeasibleOperationError(ProtocolError):
    """Raised when an operation violates solvency or feasibility constraints."""


class NotFoundError(ProtocolError):
    """Raised when an expected entity is not found in the data store."""
