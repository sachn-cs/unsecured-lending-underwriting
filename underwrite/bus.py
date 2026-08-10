"""Abstract event bus — `EventBus` (sync) and `AsyncEventBus` (async) interfaces.

Concrete implementations live in dedicated modules:
- `underwrite.local` — in-process (`LocalBus`, `AsyncLocalBus`)
- `underwrite.modal` — Modal queue (`ModalBus`)

The supporting classes are also re-exported here for backward compatibility
with code that imports them from `underwrite.bus`:

- `Queue`, `Record` (from `underwrite.dlq`)
- `Breaker` (from `underwrite.circuit`)
- `Limiter`, `DistributedLimiter` (from `underwrite.rate_limit`)
- `Guard` (from `underwrite.idempotency`)
- `Registry`, `Dispatcher` (from `underwrite.subscription`)
"""

from __future__ import annotations

__all__ = [
    "AsyncEventBus",
    "Breaker",
    "Dispatcher",
    "DistributedLimiter",
    "EventBus",
    "Guard",
    "Limiter",
    "Queue",
    "Record",
    "Registry",
]

from abc import ABC, abstractmethod
from collections.abc import Callable

from underwrite.circuit import Breaker
from underwrite.dlq import Queue, Record
from underwrite.events import Event
from underwrite.idempotency import Guard
from underwrite.rate_limit import DistributedLimiter, Limiter
from underwrite.subscription import Dispatcher, Registry


class EventBus(ABC):
    """Abstract event bus. All nano services publish and subscribe here."""

    @abstractmethod
    def publish(self, event: Event) -> str:
        """Publishes an event to all matching subscribers. Returns the event ID."""

    @abstractmethod
    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> str:
        """Registers a handler for *event_type* (use ``*`` for wildcard).

        Returns a subscription ID that can be passed to ``unsubscribe``.
        """

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription."""

    @abstractmethod
    def start(self) -> None:
        """Starts delivering buffered events."""

    @abstractmethod
    def stop(self) -> None:
        """Stops event delivery and clears all subscriptions."""

    @property
    @abstractmethod
    def dlq(self) -> Queue:
        """Returns the dead-letter queue for this bus."""

    @property
    @abstractmethod
    def idempotency(self) -> Guard:
        """Returns the idempotency guard for this bus."""


class AsyncEventBus(ABC):
    """Abstract async event bus. Same contract as EventBus but for async subscribers."""

    @abstractmethod
    async def publish(self, event: Event) -> str:
        """Publishes an event to all matching subscribers. Returns the event ID."""

    @abstractmethod
    async def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> str:
        """Registers a handler for *event_type* (use ``*`` for wildcard).

        Returns a subscription ID that can be passed to ``unsubscribe``.
        """

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Removes a previously registered subscription."""

    @abstractmethod
    async def start(self) -> None:
        """Starts delivering buffered events."""

    @abstractmethod
    async def stop(self) -> None:
        """Stops event delivery and clears all subscriptions."""

    @property
    @abstractmethod
    def dlq(self) -> Queue:
        """Returns the dead-letter queue for this bus."""

    @property
    @abstractmethod
    def idempotency(self) -> Guard:
        """Returns the idempotency guard for this bus."""
