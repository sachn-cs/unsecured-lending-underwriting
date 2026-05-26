"""Shared validation helpers for nano services.

All functions raise ``ProtocolError`` on invalid input, which is
silently caught by ``NanoService.__dispatch``, preventing state
corruption while keeping the bus alive.
"""

from __future__ import annotations

__all__ = [
    "get_finite",
    "get_in_range",
    "get_match",
    "get_non_empty",
    "get_non_negative",
    "get_positive",
    "require_finite",
    "require_in_range",
    "require_match",
    "require_non_empty",
    "require_non_negative",
    "require_positive",
]

import math
import re
from typing import Any

from underwrite.__exceptions__ import ProtocolError


def require_non_empty(value: Any, name: str) -> str:
    """Validates that *value* is a non-empty string.

    Args:
        value: The value to validate.
        name: Human-readable field name for error messages.

    Returns:
        The stripped string.

    Raises:
        ProtocolError: If *value* is not a non-empty string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{name} must be a non-empty string")
    return value.strip()


def require_finite(value: Any, name: str) -> float:
    """Validates that *value* is a finite number.

    Args:
        value: The value to validate.
        name: Human-readable field name for error messages.

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If *value* is not a finite number.
    """
    try:
        v = float(value)
    except (ValueError, TypeError) as e:
        raise ProtocolError(
            f"{name} must be a valid number, got {type(value).__name__}") from e
    if not math.isfinite(v):
        raise ProtocolError(f"{name} must be finite (got {v})")
    return v


def require_positive(value: Any, name: str) -> float:
    """Validates that *value* is a positive finite number (> 0).

    Args:
        value: The value to validate.
        name: Human-readable field name for error messages.

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If *value* is not positive.
    """
    v = require_finite(value, name)
    if v <= 0:
        raise ProtocolError(f"{name} must be positive (got {v})")
    return v


def require_non_negative(value: Any, name: str) -> float:
    """Validates that *value* is a non-negative finite number (>= 0).

    Args:
        value: The value to validate.
        name: Human-readable field name for error messages.

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If *value* is negative.
    """
    v = require_finite(value, name)
    if v < 0:
        raise ProtocolError(f"{name} must be non-negative (got {v})")
    return v


def require_in_range(value: Any, lo: float, hi: float, name: str) -> float:
    """Validates that *value* is in the open interval (*lo*, *hi*).

    Args:
        value: The value to validate.
        lo: Lower bound (exclusive).
        hi: Upper bound (exclusive).
        name: Human-readable field name for error messages.

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If *value* is outside (*lo*, *hi*).
    """
    v = require_finite(value, name)
    if not (lo < v < hi):
        raise ProtocolError(f"{name} must be in ({lo}, {hi}) (got {v})")
    return v


def require_match(pattern: str, value: Any, name: str) -> str:
    """Validates that *value* matches a regex pattern.

    Args:
        pattern: The regex pattern to match against.
        value: The value to validate.
        name: Human-readable field name for error messages.

    Returns:
        The matched string.

    Raises:
        ProtocolError: If *value* does not match *pattern*.
    """
    s = require_non_empty(value, name)
    if not re.match(pattern, s):
        raise ProtocolError(f"{name} does not match required pattern")
    return s


def get_non_empty(payload: dict[str, Any], key: str, name: str = "") -> str:
    """Returns a non-empty string from a payload dict.

    Args:
        payload: The data dictionary.
        key: The key to extract.
        name: Human-readable field name (defaults to *key*).

    Returns:
        The stripped string.

    Raises:
        ProtocolError: If the value is missing or empty.
    """
    val = payload.get(key, "")
    if isinstance(val, str):
        val = val.strip()
    return require_non_empty(val, name or key)


def get_finite(payload: dict[str, Any],
               key: str,
               default: float = 0.0,
               name: str = "") -> float:
    """Returns a finite number from a payload dict.

    Args:
        payload: The data dictionary.
        key: The key to extract.
        default: Default if *key* is missing.
        name: Human-readable field name (defaults to *key*).

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If the value is not a finite number.
    """
    return require_finite(payload.get(key, default), name or key)


def get_positive(payload: dict[str, Any],
                 key: str,
                 default: float = 1.0,
                 name: str = "") -> float:
    """Returns a positive finite number from a payload dict.

    Args:
        payload: The data dictionary.
        key: The key to extract.
        default: Default if *key* is missing.
        name: Human-readable field name (defaults to *key*).

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If the value is not positive.
    """
    return require_positive(payload.get(key, default), name or key)


def get_non_negative(payload: dict[str, Any],
                     key: str,
                     default: float = 0.0,
                     name: str = "") -> float:
    """Returns a non-negative finite number from a payload dict.

    Args:
        payload: The data dictionary.
        key: The key to extract.
        default: Default if *key* is missing.
        name: Human-readable field name (defaults to *key*).

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If the value is negative.
    """
    return require_non_negative(payload.get(key, default), name or key)


def get_in_range(payload: dict[str, Any],
                 key: str,
                 lo: float,
                 hi: float,
                 default: float,
                 name: str = "") -> float:
    """Returns a value in (*lo*, *hi*) from a payload dict.

    Args:
        payload: The data dictionary.
        key: The key to extract.
        lo: Lower bound (exclusive).
        hi: Upper bound (exclusive).
        default: Default if *key* is missing.
        name: Human-readable field name (defaults to *key*).

    Returns:
        The value as a float.

    Raises:
        ProtocolError: If the value is outside (*lo*, *hi*).
    """
    return require_in_range(payload.get(key, default), lo, hi, name or key)


def get_match(payload: dict[str, Any],
              key: str,
              pattern: str,
              name: str = "") -> str:
    """Returns a regex-matched string from a payload dict.

    Args:
        payload: The data dictionary.
        key: The key to extract.
        pattern: The regex pattern to match.
        name: Human-readable field name (defaults to *key*).

    Returns:
        The matched string.

    Raises:
        ProtocolError: If the value is missing or does not match *pattern*.
    """
    return require_match(pattern, payload.get(key, ""), name or key)
