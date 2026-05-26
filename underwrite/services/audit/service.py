"""Append-only audit ledger.  Records every domain event for compliance.

All payloads are redacted for PII before storage.  The raw event is
never persisted — only the sanitized record.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from underwrite.__events__ import Event
from underwrite.__pii import redact_payload
from underwrite.services import NanoService

logger = logging.getLogger(__name__)


class AuditService(NanoService):
    """Subscribes to all domain events and persists them to an append-only ledger.

    PII fields (aadhaar, pan, ssn, phone, email, etc.) are automatically
    redacted from the payload before recording.  In-memory ledger is
    capped at *max_ledger* entries; oldest entries are evicted first.
    """

    def __init__(self, max_ledger: int = 100000, export_url: str = "", **kwargs: Any) -> None:
        """Initialise the audit service with a bounded in-memory ledger.

        Args:
            max_ledger: Maximum number of records to keep. Oldest entries
                are evicted when the ledger exceeds this limit.
            **kwargs: Forwarded to NanoService.__init__.
        """
        super().__init__(**kwargs)
        self.__max_ledger: int = max_ledger
        self.__lock: threading.RLock = threading.RLock()
        self.__ledger: deque = deque(maxlen=max_ledger)
        self.__export_url: str = export_url
        self.__load_store()

    def handle(self, event: Event) -> None:
        """Record a redacted version of *event* to the audit ledger.

        Args:
            event: The domain event to record. PII fields are redacted
                automatically before storage.
        """
        with self.__lock:
            record: dict[str, Any] = {
                "seq": len(self.__ledger) + 1,
                "event_type": event.event_type,
                "source": event.source,
                "payload": redact_payload(dict(event.payload)),
                "correlation_id": event.correlation_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            self.__ledger.append(record)
            self.__sync_store()

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

    def export(self) -> None:
        """Export the audit ledger to the configured ``export_url``.

        Supports ``s3://bucket/path`` (requires ``boto3``) and
        ``gs://bucket/path`` (requires ``google-cloud-storage``).
        No-op if ``export_url`` is not set.
        """
        if not self.__export_url:
            return
        lines: list[str] = [
            json.dumps(r, sort_keys=True) for r in self.__ledger
        ]
        body: str = "\n".join(lines) + "\n"

        if self.__export_url.startswith("s3://"):
            self.__export_s3(body)
        elif self.__export_url.startswith("gs://"):
            self.__export_gcs(body)
        else:
            logger.warning("unsupported export URL scheme: %s",
                           self.__export_url.split("://")[0])

    def __export_s3(self, body: str) -> None:
        try:
            import boto3
        except ImportError:
            logger.warning("boto3 not available; install with: pip install underwrite[aws]")
            return
        path = self.__export_url.removeprefix("s3://")
        bucket, _, key = path.partition("/")
        try:
            client = boto3.client("s3")
            client.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
            logger.info("audit exported to s3://%s/%s (%d bytes)", bucket, key,
                        len(body))
        except Exception as exc:
            logger.exception("audit S3 export failed: %s", exc)

    def __export_gcs(self, body: str) -> None:
        try:
            from google.cloud import storage
        except ImportError:
            logger.warning(
                "google-cloud-storage not available; install with: pip install google-cloud-storage")
            return
        path = self.__export_url.removeprefix("gs://")
        bucket, _, key = path.partition("/")
        try:
            client = storage.Client()
            client.bucket(bucket).blob(key).upload_from_string(body)
            logger.info("audit exported to gs://%s/%s (%d bytes)", bucket, key,
                        len(body))
        except Exception as exc:
            logger.exception("audit GCS export failed: %s", exc)

    def save_jsonl(self, path: str, chunk_size: int = 1000) -> None:
        """Write the audit ledger to a JSONL file, streaming in chunks.

        Args:
            path: Destination file path.
            chunk_size: Records per chunk to avoid holding full ledger in memory.
        """
        with open(path, "w") as fh:
            batch: list[str] = []
            for record in self.__ledger:
                batch.append(json.dumps(record, sort_keys=True))
                if len(batch) >= chunk_size:
                    fh.write("\n".join(batch) + "\n")
                    batch.clear()
            if batch:
                fh.write("\n".join(batch) + "\n")

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

    # -- state persistence ---------------------------------------------------

    def __sync_store(self) -> None:
        """Persist the in-memory ledger to the shared store."""
        with self.__lock:
            self.store.set(f"{self.service_id}:ledger",
                           list(self.__ledger))

    def __load_store(self) -> None:
        """Restore the ledger from the shared store on startup."""
        raw = self.store.get(f"{self.service_id}:ledger")
        if raw is None or not isinstance(raw, list):
            return
        self.__ledger.clear()
        for item in raw:
            self.__ledger.append(item)
