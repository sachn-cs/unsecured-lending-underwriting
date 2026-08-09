"""Shared test helpers — reusable classes and factories.

These are imported by test files and used directly (not as pytest fixtures).
"""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event
from underwrite.__store__ import ReadStore, Store
from underwrite.services.base import Core


class BrokenStore:
    """A store stub that raises OSError on every get/set."""

    def get(self, key: str) -> None:
        raise OSError(f"mock io error for {key}")

    def set(self, key: str, value: object) -> None:
        raise OSError(f"mock io error for {key}")


class RaisingStrategy:
    """A risk strategy whose predict() always raises RuntimeError."""

    @staticmethod
    def predict(principal: float, term: float) -> float:
        msg = "model failure"
        raise RuntimeError(msg)


class BadStr:
    """An object whose __str__ raises ValueError — used to test serialization guards."""

    def __str__(self) -> str:
        raise ValueError("bad str")


class ConcreteService(Core):
    """Minimal concrete Core subclass for testing base-class error paths."""

    def handle(self, event: Event) -> None:
        pass


class FakeEmitter:
    """A fake emitter that records emitted events for test assertions.

    Can be configured to fail on specific event types (simulating step failure)
    or on all compensation events (simulating compensation failure).
    """

    def __init__(self, fail_on: set[str] | None = None, fail_compensation: bool = False):
        self.emitted: list[tuple[str, dict[str, Any]]] = []
        self._fail_on = fail_on or set()
        self._fail_compensation = fail_compensation

    def emit(self, event_type: str, payload: dict[str, Any], correlation_id: str = "") -> Event:
        if event_type in self._fail_on:
            raise RuntimeError(f"step {event_type} failed")
        if self._fail_compensation and event_type.startswith("comp."):
            raise RuntimeError(f"compensation failed for {event_type}")
        self.emitted.append((event_type, payload))
        return Event(event_type=event_type, source="test", payload=payload)


class MockStore(Store):
    """A minimal Store implementation backed by an in-memory dict."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        return key in self.data

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        return list(self.data.keys())

    def health(self) -> dict[str, Any]:
        return {"ok": True}


class MockReadStore(ReadStore):
    """A minimal read-only Store implementation backed by an in-memory dict."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self.data.get(key)

    def exists(self, key: str) -> bool:
        return key in self.data

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None

    def keys(self, pattern: str | None = None, limit: int = 0, offset: int = 0) -> list[str]:
        return list(self.data.keys())

    def health(self) -> dict[str, Any]:
        return {"ok": True}
