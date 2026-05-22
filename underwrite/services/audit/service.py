"""Append-only audit ledger.  Records every domain event for compliance.

All payloads are redacted for PII before storage.  The raw event is
never persisted — only the sanitized record.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from underwrite.__events__ import Event
from underwrite.__pii import redact_payload
from underwrite.services import NanoService

logger = logging.getLogger("underwrite")


class AuditService(NanoService):
    """Subscribes to all domain events and persists them to an append-only ledger.

    PII fields (aadhaar, pan, ssn, phone, email, etc.) are automatically
    redacted from the payload before recording.  In-memory ledger is
    capped at *max_ledger* entries; oldest entries are evicted first.
    """

    def __init__(self, max_ledger: int = 100000, **kwargs: Any) -> None:
        """Initialise the audit service with a bounded in-memory ledger.

        Args:
            max_ledger: Maximum number of records to keep. Oldest entries
                are evicted when the ledger exceeds this limit.
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(**kwargs)
        self.__max_ledger: int = max_ledger
        self.__ledger: deque = deque(maxlen=max_ledger)

    def handle(self, event: Event) -> None:
        """Record a redacted version of *event* to the audit ledger.

        Args:
            event: The domain event to record. PII fields are redacted
                automatically before storage.
        """
        record: dict[str, Any] = {
            "seq": len(self.__ledger) + 1,
            "event_type": event.event_type,
            "source": event.source,
            "payload": redact_payload(dict(event.payload)),
            "correlation_id": event.correlation_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.__ledger.append(record)

    @property
    def ledger(self) -> list[dict[str, Any]]:
        """Return a snapshot of all audit records."""
        return list(self.__ledger)

    def events_by_type(self, event_type: str) -> list[dict[str, Any]]:
        """Return all audit records matching a given event type.

        Args:
            event_type: The event type string to filter by.

        Returns:
            List of audit records with matching event_type.
        """
        return [e for e in self.__ledger if e["event_type"] == event_type]

    def save_jsonl(self, path: str) -> None:
        """Write the entire audit ledger to a JSONL file.

        Args:
            path: Destination file path.
        """
        lines: list[str] = []
        for record in self.__ledger:
            lines.append(json.dumps(record, sort_keys=True))
        Path(path).write_text("\n".join(lines) + "\n")

    def load_jsonl(self, path: str) -> None:
        """Load audit records from a JSONL file, replacing the current ledger.

        Corrupted lines are skipped and logged as warnings.

        Args:
            path: Source file path. No-op if the file does not exist.
        """
        self.__ledger.clear()
        p = Path(path)
        if not p.exists():
            return
        corrupted: int = 0
        with open(p) as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if line:
                    try:
                        self.__ledger.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        corrupted += 1
                        logger.warning("corrupted audit line %d in %s: %s", i,
                                       path, exc)
        if corrupted:
            logger.warning("audit load skipped %d corrupted line(s) from %s",
                           corrupted, path)
