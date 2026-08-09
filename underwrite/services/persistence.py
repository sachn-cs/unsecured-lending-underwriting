"""Generic store-backed repository for nano-service state persistence.

Replaces manual __sync_store / __load_store boilerplate with a reusable,
type-safe abstraction. Encapsulates key management, serialization, and
type validation in one place.

Typical usage:
    repo = StoreRepository[dict](store, f'{service_id}:data')
    data = repo.load(default={})
    repo.save(data)
"""

from __future__ import annotations

import threading
from typing import Any, Generic, TypeVar

from underwrite.__logger__ import logger
from underwrite.__store__ import Store

T = TypeVar("T")


class StoreRepository(Generic[T]):
    """Generic thread-safe repository for store-backed state.

    Handles key prefixing, serialization, and type-safe loading. Does
    *not* manage its own lock — the caller is responsible for
    concurrency control (use the service's own lock).
    """

    def __init__(self, store: Store, key: str) -> None:
        """Initialize the repository.

        Args:
            store: The shared Store backend.
            key: Store key to read/write state under.
        """
        self.store = store
        self.key = key

    def load(self, default: T | None = None) -> T | None:
        """Load state from the store.

        Args:
            default: Value returned when the key is missing or the read
                fails.

        Returns:
            The deserialized state, or *default* if the key does not
            exist or the read fails.
        """
        try:
            raw = self.store.get(self.key)
            if raw is None:
                return default
            return self.deserialize(raw)
        except (OSError, ValueError, TypeError, KeyError):
            logger.exception("failed to load {} from store", self.key)
            return default

    def save(self, data: T) -> None:
        """Persist state to the store.

        Args:
            data: The state to persist.

        Raises:
            StoreError: If the store write fails.
        """
        self.store.set(self.key, self.serialize(data))

    def deserialize(self, raw: Any) -> T:
        """Override in subclasses for custom deserialization."""
        return raw

    def serialize(self, data: T) -> Any:
        """Override in subclasses for custom serialization."""
        return data


class TypedStoreRepository(StoreRepository[T]):
    """A StoreRepository that validates the loaded value type.

    If the stored value is not an instance of *expected_type* the
    repository returns *default*, preventing silent data corruption.
    """

    def __init__(
        self,
        store: Store,
        key: str,
        expected_type: type[T] | tuple[type[T], ...],
    ) -> None:
        """Initialize the typed repository.

        Args:
            store: The shared Store backend.
            key: Store key to read/write state under.
            expected_type: Type or tuple of types that loaded values
                must be instances of.
        """
        super().__init__(store, key)
        self.expected_type = expected_type

    def load(self, default: T | None = None) -> T | None:
        raw = self.store.get(self.key)
        if raw is None:
            return default
        if not isinstance(raw, self.expected_type):
            logger.warning(
                "expected {} for key {}, got {} - returning default",
                self.expected_type,
                self.key,
                type(raw).__name__,
            )
            return default
        return raw


class BatchedStoreRepository(TypedStoreRepository[T]):
    """A TypedStoreRepository with batched persistence.

    Instead of writing to the store on every save() call, accumulates
    a counter and only triggers the actual sync every *sync_interval*
    incr_and_maybe_sync() calls. Useful for high-frequency state
    updates where O(n) serialization is a concern.

    Subclasses must call incr_and_maybe_sync() or force_sync() to
    persist; a plain save() still writes immediately.
    """

    def __init__(
        self,
        store: Store,
        key: str,
        expected_type: type | tuple[type, ...],
        sync_interval: int = 10,
    ) -> None:
        """Initialize the batched repository.

        Args:
            store: The shared Store backend.
            key: Store key to read/write state under.
            expected_type: Type constraint for loaded values.
            sync_interval: Persist only every N incr_and_maybe_sync()
                calls. Minimum value is 1.
        """
        super().__init__(store, key, expected_type)
        self.__batch_lock: threading.Lock = threading.Lock()
        self.__sync_interval: int = max(sync_interval, 1)
        self.__sync_counter: int = 0
        # Cache the most recent data so a force_sync on shutdown
        # persists the latest state even if the interval was
        # never reached. incr_and_maybe_sync() updates this on
        # every call and saves the latest value when the counter
        # trips.
        self.__pending: T | None = None

    def incr_and_maybe_sync(self, data: T) -> bool:
        """Increment the counter and trigger sync if threshold reached.

        Caches *data* so the next sync writes the latest state,
        not the state that happened to be passed at the trip
        point. Callers that want a strict batched snapshot of
        a specific value should use save() directly.

        Args:
            data: The latest state; will be persisted on the next
                sync boundary.

        Returns:
            True if a sync was triggered, False otherwise.
        """
        with self.__batch_lock:
            self.__pending = data
            self.__sync_counter += 1
            if self.__sync_counter >= self.__sync_interval:
                self.__sync_counter = 0
                pending = data
                self.__pending = None
                self.save(pending)
                return True
        return False

    def force_sync(self, data: T) -> None:
        """Immediately persist regardless of the counter.

        Args:
            data: The state to persist.
        """
        with self.__batch_lock:
            self.__sync_counter = 0
            self.save(data)

    def reset_counter(self) -> None:
        """Reset the internal sync counter without persisting."""
        with self.__batch_lock:
            self.__sync_counter = 0
