"""Thread-local correlation context shared across modules.

The correlation id for the current execution context lives here so that
logging (``underwrite.logger``) and the service layer
(``underwrite.services.base``) can read and set it without importing each
other.

The context is a :class:`contextvars.ContextVar` rather than a
``threading.local`` because it is per-thread by default, composes with
``asyncio`` tasks, and carries no shared mutable state.
"""

from __future__ import annotations

import contextvars

__all__ = ["correlation_context", "get_log_correlation_id"]

correlation_context: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_context", default="")


def get_log_correlation_id() -> str:
    """Return the correlation id for the current context, or an empty string.

    Returns:
        The current correlation id, or ``""`` when none is set.
    """
    return correlation_context.get()
