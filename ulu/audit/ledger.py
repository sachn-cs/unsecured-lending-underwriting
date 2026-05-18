"""Append-only audit ledger with deterministic JSONL serialization."""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LedgerEvent:
    """Represents a single immutable audit event."""

    seq: int
    event_type: str
    payload: dict[str, Any]
    timestamp_utc: str


class AppendOnlyLedger:
    """In-memory append-only ledger with JSONL persistence."""

    def __init__(self) -> None:
        self.events_store: list[LedgerEvent] = []

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def append(self, event_type: str, payload: Mapping[str, Any]) -> LedgerEvent:
        """Appends an event and returns the inserted record."""
        event = LedgerEvent(
            seq=len(self.events_store) + 1,
            event_type=event_type,
            payload=dict(payload),
            timestamp_utc=self.utc_now_iso(),
        )
        self.events_store.append(event)
        return event

    def events(self) -> list[LedgerEvent]:
        """Returns a copy of all events in insertion order."""
        return list(self.events_store)

    def to_jsonl(self) -> str:
        """Serializes events as newline-delimited JSON records."""
        return "\n".join(json.dumps(asdict(event), sort_keys=True) for event in self.events_store)

    def save_jsonl(self, path: str | Path) -> None:
        """Writes ledger events to JSONL file."""
        suffix = "\n" if self.events_store else ""
        Path(path).write_text(self.to_jsonl() + suffix, encoding="utf-8")

    @classmethod
    def event_from_row(cls, row: Mapping[str, Any]) -> LedgerEvent:
        """Builds a `LedgerEvent` from a deserialized JSON mapping."""
        return LedgerEvent(
            seq=int(row["seq"]),
            event_type=str(row["event_type"]),
            payload=dict(row["payload"]),
            timestamp_utc=str(row["timestamp_utc"]),
        )

    @classmethod
    def stream_jsonl(cls, path: str | Path) -> Generator[LedgerEvent, None, None]:
        """Yields ledger events from a JSONL file without loading all into memory."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"ledger file not found: {path}")

        with open(file_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                yield cls.event_from_row(row)

    @classmethod
    def load_jsonl(cls, path: str | Path) -> AppendOnlyLedger:
        """Loads a ledger from JSONL file."""
        ledger = cls()
        for event in cls.stream_jsonl(path):
            ledger.events_store.append(event)

        for index, event in enumerate(ledger.events_store, start=1):
            if event.seq != index:
                raise ValueError("invalid ledger sequence: non-contiguous seq")
        return ledger
