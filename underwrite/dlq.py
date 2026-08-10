"""Dead-letter queue — captures events that failed processing.

Evicts oldest entries when *max_records* is exceeded to prevent
unbounded memory growth. Optionally persists to a ``Store`` for
durability across restarts. Persistence is batched — the store is
only written every *sync_interval* ``put()`` calls to avoid O(n)
serialisation overhead on every event.

PII is redacted at the put() boundary via ``redact_event`` so the
DLQ never carries PAN, Aadhaar, or other sensitive identifiers.
"""

from __future__ import annotations

__all__ = [
    "Queue",
    "Record",
]

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from underwrite.events import Event
from underwrite.logger import logger
from underwrite.pii import redact_event
from underwrite.store import Store


@dataclass(frozen=True, slots=True)
class Record:
    """A single failed event and the error that caused the failure."""

    event: Event
    error: str
    subscriber_id: str
    timestamp: float = field(default_factory=time.time)


class Queue:
    """Captures events that failed processing.

    Evicts oldest entries when *max_records* is exceeded to prevent
    unbounded memory growth. Optionally persists to a ``Store`` for
    durability across restarts.
    """

    def __init__(self, max_records: int = 10000, store: Store | None = None, sync_interval: int = 10) -> None:
        self.lock: threading.Lock = threading.Lock()
        self.records: deque[Record] = deque(maxlen=max_records)
        self.max_records: int = max_records
        self.store: Store | None = store
        self.sync_interval: int = max(sync_interval, 1)
        self.sync_counter: int = 0
        if store is not None:
            self.__load_store()

    @staticmethod
    def event_to_dict(event: Event) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "source": event.source,
            "source_key": event.source_key,
            "timestamp": event.timestamp,
            "payload": event.payload,
            "correlation_id": event.correlation_id,
            "signature": event.signature,
            "trace_id": event.trace_id,
            "parent_span_id": event.parent_span_id,
        }

    @staticmethod
    def event_from_dict(d: dict[str, Any]) -> Event:
        return Event(**d)

    @staticmethod
    def record_to_dict(r: Record) -> dict[str, Any]:
        return {
            "event": Queue.event_to_dict(r.event),
            "error": r.error,
            "subscriber_id": r.subscriber_id,
            "timestamp": r.timestamp,
        }

    @staticmethod
    def record_from_dict(d: dict[str, Any]) -> Record:
        return Record(
            event=Queue.event_from_dict(d["event"]),
            error=d["error"],
            subscriber_id=d["subscriber_id"],
            timestamp=d["timestamp"],
        )

    def __load_store(self) -> None:
        store = self.store
        if store is None:
            return
        raw = store.get("bus:dlq")
        if raw is not None:
            if isinstance(raw, list):
                valid: list[Record] = []
                skipped = 0
                for r in raw:
                    if isinstance(r, dict) and "event" in r:
                        valid.append(self.record_from_dict(r))
                    else:
                        skipped += 1
                if skipped:
                    logger.warning("skipped {} corrupted DLQ records on load", skipped)
                self.records = deque(valid[-self.max_records :], maxlen=self.max_records)
            else:
                logger.warning(
                    "corrupted DLQ store data (expected list, got {}), starting with empty DLQ", type(raw).__name__
                )

    def __sync_store(self) -> None:
        store = self.store
        if store is None:
            return
        try:
            store.set("bus:dlq", [self.record_to_dict(r) for r in self.records])
        except Exception:
            logger.exception("failed to persist DLQ records to store — DLQ is now memory-only until the store recovers")

    def __should_sync(self) -> bool:
        self.sync_counter += 1
        if self.sync_counter >= self.sync_interval:
            self.sync_counter = 0
            return True
        return False

    @property
    def count(self) -> int:
        """Returns the number of dead-letter records."""
        with self.lock:
            return len(self.records)

    def put(self, event: Event, error: str, subscriber_id: str) -> None:
        """Records a failed event.

        Args:
            event: The event that failed.
            error: Description of the failure.
            subscriber_id: Identifier of the subscriber that failed.
        """
        sanitized_event = redact_event(event)
        with self.lock:
            self.records.append(Record(event=sanitized_event, error=error, subscriber_id=subscriber_id))
            if self.__should_sync():
                self.__sync_store()

    def clear(self) -> None:
        """Removes all dead-letter records."""
        with self.lock:
            self.records.clear()
            self.sync_counter = 0
            self.__sync_store()

    def replay(self, bus: Any, max_count: int = 0) -> int:
        """Re-publishes dead-letter events to a bus.

        Events are removed from the DLQ *before* replay to prevent
        concurrent ``dead()`` calls from re-adding them while we
        iterate. If an individual replay fails the event is put back
        on the DLQ with a new error entry.

        Args:
            bus: The event bus to publish on.
            max_count: Maximum events to replay (0 = all).

        Returns:
            Number of events replayed.
        """
        with self.lock:
            to_replay = list(self.records)
            if max_count > 0:
                to_replay = to_replay[:max_count]
            for _ in range(len(to_replay)):
                self.records.popleft()
            self.sync_counter = 0
            self.__sync_store()
        replayed = 0
        for record in to_replay:
            try:
                bus.publish(record.event)
                replayed += 1
            except Exception:
                logger.exception("DLQ replay failed for event {}", record.event.event_id)
                self.put(record.event, f"replay_failed: {record.error}", record.subscriber_id)
        return replayed
