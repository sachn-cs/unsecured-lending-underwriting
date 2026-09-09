# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for DLQ size and persistence bounds."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from underwrite.dlq import Queue
from underwrite.message import Message
from underwrite.store import Sqlite


def _event(event_id: str = "evt-1") -> Message:
    return Message(
        event_id=event_id,
        event_type="demo.event",
        source="test",
        source_key="",
        timestamp="2026-09-09T00:00:00+00:00",
        payload={"hello": "world"},
    )


class TestDlqSizeBounds:
    def test_max_records_caps_in_memory_size(self) -> None:
        dlq = Queue(max_records=8)
        for i in range(50):
            dlq.put(_event(event_id=f"evt-{i}"), "boom", "subscriber")
        assert dlq.count == 8

    def test_max_bytes_caps_persisted_blob(self) -> None:
        store = Sqlite(":memory:")
        # Each event roughly 600 bytes when serialized. Set max_bytes
        # to fit ~3 events.
        dlq = Queue(max_records=1_000, store=store, sync_interval=1, max_bytes=2_000)
        for i in range(20):
            dlq.put(_event(event_id=f"evt-{i}-{i * 1000}"), "boom", "subscriber")
        assert dlq.count <= 5

    def test_constructor_rejects_invalid_args(self) -> None:
        with pytest.raises(ValueError):
            Queue(max_records=0)
        with pytest.raises(ValueError):
            Queue(max_bytes=0)

    def test_replay_with_zero_replays_all(self) -> None:
        dlq = Queue(max_records=10)
        for i in range(5):
            dlq.put(_event(event_id=f"evt-{i}"), "boom", "subscriber")
        bus = MagicMock()
        replayed = dlq.replay(bus)
        assert replayed == 5
        assert dlq.count == 0


class TestDlqPoisonMessageDeduplication:
    def test_repeated_event_id_updates_record(self) -> None:
        dlq = Queue(max_records=100)
        dlq.put(_event("poison"), "boom", "subscriber")
        dlq.put(_event("poison"), "boom", "subscriber")
        dlq.put(_event("poison"), "still boom", "subscriber")
        assert dlq.count == 1
        # After replay clears, the next put should still record one entry.
        records = list(dlq.records.values())
        assert records[0].repeat_count == 3
        assert records[0].error == "still boom"


class TestDlqPersistence:
    def test_load_truncates_to_max_records(self) -> None:
        store = Sqlite(":memory:")
        dlq = Queue(max_records=4, store=store, sync_interval=1)
        for i in range(20):
            dlq.put(_event(event_id=f"evt-{i:02d}"), "boom", "subscriber")
        # Re-load with a smaller cap.
        reloaded = Queue(max_records=4, store=store, sync_interval=1)
        assert reloaded.count == 4
        # The most-recent four event ids are preserved.
        kept_ids = list(reloaded.records.keys())
        assert kept_ids == [f"evt-{i:02d}" for i in range(16, 20)]

    def test_sync_failure_does_not_lose_in_memory_state(self) -> None:
        store = Sqlite(":memory:")
        dlq = Queue(max_records=4, store=store, sync_interval=1)
        dlq.put(_event("evt-1"), "boom", "subscriber")
        # Wipe the store mid-flight; the in-memory deque survives.
        store.delete("bus:dlq")
        dlq.put(_event("evt-2"), "boom", "subscriber")
        assert dlq.count == 2
