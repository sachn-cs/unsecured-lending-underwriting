"""Generic, reusable utilities — free functions, no state, no classes.

Each utility is small, single-purpose, and reused in 2+ places.

For domain-specific helpers, use the dedicated module:
- PII redaction       → pii.py
- Money / Rate        → value_objects.py
- Indian calendar     → calendar.py
- Amortization math    → amortization.py
- Indian formats      → indian_format.py
- Payload validation  → validate.py
"""

from __future__ import annotations

__all__ = [
    "chunked",
    "clamp",
    "first",
    "generate_id",
    "merge",
    "now_iso",
    "safe_divide",
]

import os
import socket
import struct
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any, TypeVar

T = TypeVar("T")


def generate_id() -> str:
    """Generate a BSON-style 24-character hex identifier.

    Format: timestamp[4] + machine[3] + pid[2] + counter[3] = 24 hex chars.
    Globally unique per process; collision-resistant across processes.
    """
    timestamp = struct.pack(">I", int(time.time()))
    machine = socket.gethostname().encode()[:3].ljust(3, b"\x00")
    pid = struct.pack(">H", os.getpid())
    counter = os.urandom(3)
    return (timestamp + machine + pid + counter).hex()


def now_iso() -> str:
    """Return current UTC time as an ISO 8601 string with timezone."""
    return datetime.now(timezone.utc).isoformat()


def chunked(items: Iterable[T], size: int) -> Iterable[list[T]]:
    """Yield successive *size*-element lists from *items*."""
    if size <= 0:
        raise ValueError(f"chunk size must be positive, got {size}")
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def first(items: Iterable[T], predicate: Callable[[T], bool] | None = None) -> T | None:
    """Return first item (matching *predicate* if given) or None if *items* is empty."""
    for item in items:
        if predicate is None or predicate(item):
            return item
    return None


def clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* into the range [*low*, *high*]."""
    if low > high:
        raise ValueError(f"clamp: low ({low}) > high ({high})")
    return max(low, min(value, high))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Return numerator/denominator, or *default* if denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def merge(*dicts: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict that is the shallow merge of *dicts* (later wins)."""
    result: dict[str, Any] = {}
    for d in dicts:
        if d:
            result.update(d)
    return result
