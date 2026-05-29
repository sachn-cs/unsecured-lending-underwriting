"""Event schema registry — per-event-type payload validation with versioning.

Each event type registered in the schema registry declares its expected
payload fields and a version number.  When an event is published or
handled, its payload can be validated against the registered schema.

Usage::

    from underwrite.__schema__ import registry, EventSchema

    registry.register("loan.originated", EventSchema(
        version=1,
        fields={
            "borrower": str,
            "principal": float,
            "term": float,
        },
    ))

    registry.validate("loan.originated", {"borrower": "alice"})  # raises
"""

from __future__ import annotations

__all__ = [
    "EventSchema",
    "SchemaRegistry",
    "registry",
    "SchemaValidationError",
]

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SchemaValidationError(ValueError):
    """Raised when an event payload does not match its registered schema."""


class EventSchema:
    """Describes the expected payload of a single event type at a given version.

    Attributes:
        version: Schema version (incremented when fields change).
        description: Human-readable description of the event.
        fields: Dict mapping field name → Python type.
        required: Set of field names that must be present.
    """

    def __init__(
        self,
        version: int = 1,
        description: str = "",
        fields: dict[str, type] | None = None,
        required: set[str] | None = None,
    ) -> None:
        self.version: int = version
        self.description: str = description
        self.fields: dict[str, type] = fields or {}
        self.required: set[str] = required or set(self.fields)

    def validate(self, payload: Any) -> None:
        """Validate *payload* against this schema.

        Args:
            payload: The event payload to check.

        Raises:
            SchemaValidationError: If validation fails.
        """
        if not isinstance(payload, dict):
            raise SchemaValidationError(
                f"expected dict payload, got {type(payload).__name__}")

        for field in self.required:
            if field not in payload:
                raise SchemaValidationError(
                    f"missing required field: {field!r}")

        for key, value in payload.items():
            expected = self.fields.get(key)
            if expected is None:
                continue
            if not isinstance(value, expected):
                raise SchemaValidationError(
                    f"field {key!r}: expected {expected.__name__}, "
                    f"got {type(value).__name__}")


class SchemaRegistry:
    """Registry of event schemas keyed by event type name."""

    def __init__(self) -> None:
        self._schemas: dict[str, EventSchema] = {}

    def register(self, event_type: str, schema: EventSchema) -> None:
        """Register a schema for *event_type*.

        Raises:
            ValueError: If a schema for *event_type* is already registered
                with a version >= the new schema's version.
        """
        existing = self._schemas.get(event_type)
        if existing is not None and existing.version >= schema.version:
            raise ValueError(
                f"schema for {event_type!r} already registered "
                f"at version {existing.version} >= {schema.version}")
        self._schemas[event_type] = schema
        logger.debug("registered schema for %s v%s", event_type, schema.version)

    def get(self, event_type: str) -> EventSchema | None:
        """Return the registered schema for *event_type*, or ``None``."""
        return self._schemas.get(event_type)

    def validate(self, event_type: str, payload: Any) -> None:
        """Validate *payload* against the registered schema for *event_type*.

        Raises:
            SchemaValidationError: If no schema is registered or validation
                fails.
        """
        schema = self._schemas.get(event_type)
        if schema is None:
            logger.debug("no schema registered for %s, skipping validation",
                         event_type)
            return
        schema.validate(payload)

    def __contains__(self, event_type: str) -> bool:
        return event_type in self._schemas


registry: SchemaRegistry = SchemaRegistry()
