# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Dead-letter queue — captures events that failed processing.

Evicts oldest entries when *max_records* is exceeded to prevent
unbounded memory growth. Optionally persists to a ``Store`` for
durability across restarts. Persistence is batched — the store is
only written every *sync_interval* ``put()`` calls to avoid O(n)
serialisation overhead on every event.

The queue deduplicates by ``event_id`` so a poison message that fails
on every redelivery does not fill the queue with identical records;
instead each repeat increments a ``repeat_count`` and updates the
``last_error`` / ``last_seen`` fields.

PII is redacted at the ``put()`` boundary via ``redact_event`` so the
DLQ never carries PAN, Aadhaar, or other sensitive identifiers.
"""

from __future__ import annotations

__all__ = [
    "Queue",
    "Record",
]

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from underwrite.logger import logger
from underwrite.message import Message
from underwrite.pii import redact_event
from underwrite.store import Sqlite, Store


@dataclass(frozen=True, slots=True)
class Record:
    """A single failed event and the error that caused the failure."""

    event: Message
    error: str
    subscriber_id: str
    timestamp: float = field(default_factory=time.time)
    repeat_count: int = 1


class Queue:
    """Captures events that failed processing.

    Evicts oldest entries when *max_records* is exceeded to prevent
    unbounded memory growth. Optionally persists to a ``Store`` for
    durability across restarts.

    The queue deduplicates by ``event.event_id`` so a poison message
    that fails on every redelivery does not fill the queue with
    identical records; each repeat increments ``repeat_count`` and
    updates the ``error`` and ``timestamp`` fields.
    """

    def __init__(
        self,
        max_records: int = 10000,
        store: Store | Sqlite | None = None,
        sync_interval: int = 10,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        """Initializes the dead-letter queue.

        Args:
            max_records: Maximum number of records to keep in memory.
                Once exceeded, the oldest records are evicted.
            store: Optional persistence backend. When provided, the
                queue is loaded on construction and synced periodically.
            sync_interval: Number of ``put`` calls between store syncs.
                Set to 1 to flush every put, larger values to amortize
                the cost across many puts.
            max_bytes: Soft cap on the serialized size of the persistent
                blob. When the next sync would exceed this size, the
                oldest records are trimmed first. Defaults to 16 MiB.
        """
        if max_records <= 0:
            raise ValueError(f"max_records must be > 0, got {max_records}")
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be > 0, got {max_bytes}")
        self.lock: threading.Lock = threading.Lock()
        # OrderedDict preserves insertion order; we evict from the front
        # when we exceed max_records.
        self.records: "OrderedDict[str, Record]" = OrderedDict()
        self.max_records: int = max_records
        self.max_bytes: int = max_bytes
        self.store: Store | Sqlite | None = store
        self.sync_interval: int = max(sync_interval, 1)
        self.sync_counter: int = 0
        if store is not None:
            self.load_store()

    @staticmethod
    def event_to_dict(event: Message) -> dict[str, Any]:
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
    def event_from_dict(d: dict[str, Any]) -> Message:
        return Message(**d)

    @staticmethod
    def record_to_dict(r: Record) -> dict[str, Any]:
        return {
            "event": Queue.event_to_dict(r.event),
            "error": r.error,
            "subscriber_id": r.subscriber_id,
            "timestamp": r.timestamp,
            "repeat_count": r.repeat_count,
        }

    @staticmethod
    def record_from_dict(d: dict[str, Any]) -> Record:
        return Record(
            event=Queue.event_from_dict(d["event"]),
            error=d["error"],
            subscriber_id=d["subscriber_id"],
            timestamp=d.get("timestamp", time.time()),
            repeat_count=int(d.get("repeat_count", 1)),
        )

    def load_store(self) -> None:
        store = self.store
        if store is None:
            return
        raw = store.get("bus:dlq")
        if raw is None:
            return
        if not isinstance(raw, list):
            logger.warning(
                "corrupted DLQ store data (expected list, got {}), starting with empty DLQ",
                type(raw).__name__,
            )
            return
        valid: list[Record] = []
        skipped = 0
        for r in raw:
            if isinstance(r, dict) and "event" in r:
                valid.append(self.record_from_dict(r))
            else:
                skipped += 1
        if skipped:
            logger.warning("skipped {} corrupted DLQ records on load", skipped)
        # Keep the most recent max_records, by timestamp order.
        valid.sort(key=lambda r: r.timestamp)
        for record in valid[-self.max_records :]:
            self.records[record.event.event_id] = record
        # Trim from the front if we still exceed the byte cap.
        self._enforce_caps()

    def _enforce_caps(self) -> None:
        """Trim oldest entries until we satisfy both bounds."""
        while len(self.records) > self.max_records:
            self.records.popitem(last=False)
        while self._serialized_size() > self.max_bytes and self.records:
            self.records.popitem(last=False)

    def _serialized_size(self) -> int:
        import json as json_mod

        try:
            return len(
                json_mod.dumps([self.record_to_dict(r) for r in self.records.values()]).encode("utf-8"),
            )
        except (TypeError, ValueError):
            return 0

    def sync_store(self) -> None:
        store = self.store
        if store is None:
            return
        try:
            payload = [self.record_to_dict(r) for r in self.records.values()]
            store.set("bus:dlq", payload)
        except Exception:
            logger.exception(
                "failed to persist DLQ records to store — DLQ is now memory-only until the store recovers",
            )

    def should_sync(self) -> bool:
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

    def put(self, event: Message, error: str, subscriber_id: str) -> None:
        """Records a failed event.

        Args:
            event: The event that failed.
            error: Description of the failure.
            subscriber_id: Identifier of the subscriber that failed.
        """
        sanitized_event = redact_event(event)
        with self.lock:
            existing = self.records.get(sanitized_event.event_id)
            if existing is not None:
                self.records[sanitized_event.event_id] = Record(
                    event=existing.event,
                    error=error,
                    subscriber_id=subscriber_id,
                    timestamp=time.time(),
                    repeat_count=existing.repeat_count + 1,
                )
            else:
                self.records[sanitized_event.event_id] = Record(
                    event=sanitized_event,
                    error=error,
                    subscriber_id=subscriber_id,
                )
            self._enforce_caps()
            if self.should_sync():
                self.sync_store()

    def clear(self) -> None:
        """Removes all dead-letter records."""
        with self.lock:
            self.records.clear()
            self.sync_counter = 0
            self.sync_store()

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
            to_replay = list(self.records.values())
            if max_count > 0:
                to_replay = to_replay[:max_count]
            for record in to_replay:
                self.records.pop(record.event.event_id, None)
            self.sync_counter = 0
            self.sync_store()
        replayed = 0
        for record in to_replay:
            try:
                bus.publish(record.event)
                replayed += 1
            except Exception:
                logger.exception("DLQ replay failed for event {}", record.event.event_id)
                self.put(record.event, f"replay_failed: {record.error}", record.subscriber_id)
        return replayed