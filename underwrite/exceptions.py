"""Custom exceptions for the underwrite platform."""

from __future__ import annotations

__all__ = [
    "AuthzError",
    "BusError",
    "CircuitBreakerOpenError",
    "ConfigurationError",
    "IdentityError",
    "InfeasibleOperationError",
    "InvariantViolationError",
    "MigrationError",
    "ProtocolError",
    "RateLimitError",
    "SagaError",
    "ServiceNotFoundError",
    "StoreError",
    "UnderwriteError",
    "UnknownUserError",
]


class UnderwriteError(Exception):
    """Base exception for all underwrite errors."""


class ConfigurationError(UnderwriteError):
    """Raised when configuration is invalid or missing."""


class ServiceNotFoundError(UnderwriteError):
    """Raised when a requested service is not registered."""


class IdentityError(UnderwriteError):
    """Raised on identity / key-management failures."""


class BusError(UnderwriteError):
    """Raised on event-bus failures."""


class StoreError(UnderwriteError):
    """Raised on state-store failures."""


class ProtocolError(UnderwriteError):
    """Raised on mechanism protocol violations."""


class UnknownUserError(ProtocolError):
    """Raised when an operation references a non-existent user."""


class InvariantViolationError(ProtocolError):
    """Raised when a state invariant is broken."""


class InfeasibleOperationError(ProtocolError):
    """Raised when an operation cannot be satisfied (e.g. insufficient credit)."""


class AuthzError(UnderwriteError):
    """Raised when an event is denied by the access-control policy."""


class RateLimitError(UnderwriteError):
    """Raised when a subscriber exceeds its rate limit."""


class MigrationError(UnderwriteError):
    """Raised when schema migration fails."""


class SagaError(UnderwriteError):
    """Raised when a saga step fails and rollback is triggered."""


class CircuitBreakerOpenError(UnderwriteError):
    """Raised when a circuit breaker is in the open state."""
