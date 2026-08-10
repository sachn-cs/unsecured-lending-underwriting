# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for event schema registry (EventSchema, SchemaRegistry)."""

from __future__ import annotations

import pytest

from underwrite.schema import EventSchema, SchemaRegistry, SchemaValidationError


class TestEventSchema:
    def test_validates_required_fields(self) -> None:
        schema = EventSchema(
            version=1,
            fields={"borrower": str, "principal": float},
            required={"borrower"},
        )
        schema.validate({"borrower": "alice", "principal": 10000.0})

    def test_rejects_missing_required_field(self) -> None:
        schema = EventSchema(
            version=1,
            fields={"borrower": str},
            required={"borrower"},
        )
        with pytest.raises(SchemaValidationError, match="missing required"):
            schema.validate({})

    def test_rejects_wrong_type(self) -> None:
        schema = EventSchema(
            version=1,
            fields={"principal": float},
        )
        with pytest.raises(SchemaValidationError, match="expected float"):
            schema.validate({"principal": "not_a_number"})

    def test_rejects_non_dict_payload(self) -> None:
        schema = EventSchema(version=1)
        with pytest.raises(SchemaValidationError, match="expected dict"):
            schema.validate("bad payload")

    def test_unknown_fields_are_ignored(self) -> None:
        schema = EventSchema(
            version=1,
            fields={"borrower": str},
        )
        schema.validate({"borrower": "alice", "extra": "ignored"})


class TestSchemaRegistry:
    def test_register_and_get(self) -> None:
        registry = SchemaRegistry()
        schema = EventSchema(version=1, fields={"amount": float})
        registry.register("payment.received", schema)
        assert registry.get("payment.received") is schema

    def test_get_unknown_returns_none(self) -> None:
        registry = SchemaRegistry()
        assert registry.get("nonexistent") is None

    def test_validate_without_schema_skips(self) -> None:
        registry = SchemaRegistry()
        registry.validate("unknown.event", {"key": "value"})

    def test_validate_with_schema(self) -> None:
        registry = SchemaRegistry()
        registry.register(
            "loan.originated",
            EventSchema(version=1, fields={"principal": float}),
        )
        registry.validate("loan.originated", {"principal": 10000.0})

    def test_rejects_upgrade_with_older_version(self) -> None:
        registry = SchemaRegistry()
        registry.register(
            "test.event",
            EventSchema(version=2, fields={"a": str}),
        )
        with pytest.raises(ValueError, match="already registered"):
            registry.register(
                "test.event",
                EventSchema(version=1, fields={"a": str}),
            )

    def test_allows_upgrade_with_newer_version(self) -> None:
        registry = SchemaRegistry()
        registry.register(
            "test.event",
            EventSchema(version=1, fields={"a": str}),
        )
        registry.register(
            "test.event",
            EventSchema(version=2, fields={"a": str, "b": float}),
        )
        result = registry.get("test.event")
        assert result is not None
        assert result.version == 2

    def test_contains(self) -> None:
        registry = SchemaRegistry()
        registry.register("evt", EventSchema(version=1))
        assert "evt" in registry
        assert "other" not in registry
