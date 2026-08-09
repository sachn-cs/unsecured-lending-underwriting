"""Append-only audit ledger. Records every domain event for compliance.

All payloads are redacted for PII before storage. The raw event is
never persisted - only the sanitized record.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from underwrite.__events__ import Event
from underwrite.__logger__ import logger
from underwrite.__pii import PIISanitizer
from underwrite.services.base import StatefulService
from underwrite.services.persistence import BatchedStoreRepository

_sanitizer = PIISanitizer()

class AuditHandler(StatefulService):
    """Subscribes to all domain events and persists them to an append-only ledger.

    PII fields (aadhaar, pan, ssn, phone, email, etc.) are automatically
    redacted from the payload before recording. In-memory ledger is
    capped at *max_ledger* entries. Persistence is batched via
    BatchedStoreRepository.
    """

    SYNC_INTERVAL: int = 10

    def __init__(self, max_ledger: int = 100000, export_url: str = "", **kwargs: Any) -> None:
        """Initialize the audit service with a bounded in-memory ledger.

        Args:
            max_ledger: Maximum number of records to keep. Oldest entries
                are evicted when the ledger exceeds this limit.
            export_url: Optional URL for exporting the ledger
                (s3:// or gs://).
            **kwargs: Forwarded to NanoService.__init__.

        """
        super().__init__(**kwargs)
        self.__max_ledger: int = max_ledger
        self._ledger: deque = deque(maxlen=max_ledger)
        self._event_index: dict[str, list[dict[str, Any]]] = {}
        self.__export_url: str = export_url
        self.repo: BatchedStoreRepository[list[dict[str, Any]]] = self.batched_repo(
            "ledger", list, sync_interval=self.SYNC_INTERVAL
        )

    def start(self) -> None:
        """Start the service and load persisted ledger state.

        Heavy I/O is deferred from __init__ to start() so that
        constructing the service does not require a reachable store.
        """
        super().start()
        loaded = self.repo.load(default=[])
        if loaded:
            self._ledger.extend(loaded)
            for r in loaded:
                et = r.get("event_type")
                if et:
                    self._event_index.setdefault(et, []).append(r)

    def handle(self, event: Event) -> None:
        """Record a redacted version of event to the audit ledger.

        Args:
            event: The domain event to record. PII fields are redacted
                before storage.

        """
        with self.state_lock:
            record: dict[str, Any] = {
                "seq": len(self._ledger) + 1,
                "event_type": event.event_type,
                "source": event.source,
                "payload": _sanitizer.sanitize(dict(event.payload)),
                "correlation_id": event.correlation_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            self._ledger.append(record)
            self._event_index.setdefault(record["event_type"], []).append(record)
            if len(self._event_index) > self.__max_ledger * 2:
                excess = len(self._event_index) - self.__max_ledger
                for _ in range(excess):
                    try:
                        self._event_index.pop(next(iter(self._event_index)))
                    except StopIteration:
                        break
            self.repo.incr_and_maybe_sync(list(self._ledger))

    @property
    def ledger(self) -> list[dict[str, Any]]:
        """Return a snapshot of all audit records."""
        with self.state_lock:
            return list(self._ledger)

    def events_by_type(self, event_type: str) -> list[dict[str, Any]]:
        """Return all audit records matching a given event type.

        Args:
            event_type: The event type string to filter by.

        Returns:
            List of audit records with matching event_type.

        """
        with self.state_lock:
            return list(self._event_index.get(event_type, []))

    def export(self) -> None:
        """Export the audit ledger to the configured export_url.

        Supports s3://bucket/path (requires boto3) and
        gs://bucket/path (requires google-cloud-storage).
        No-op if export_url is not set.
        """
        if not self.__export_url:
            return
        lines: list[str] = [json.dumps(r, sort_keys=True) for r in self._ledger]
        body: str = "\n".join(lines) + "\n"

        if self.__export_url.startswith("s3://"):
            self.__export_s3(body)
        elif self.__export_url.startswith("gs://"):
            self.__export_gcs(body)
        else:
            logger.warning("unsupported export URL scheme: {}", self.__export_url.split("://")[0])

    def __export_s3(self, body: str) -> None:
        """Export audit data to S3.

        Args:
            body: JSONL-formatted audit data as a string.

        """
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
            logger.info("audit exported to s3://{}/{} ({} bytes)", bucket, key, len(body))
        except (OSError, ValueError, TypeError):
            logger.exception("audit S3 export failed")

    def __export_gcs(self, body: str) -> None:
        """Export audit data to GCS.

        Args:
            body: JSONL-formatted audit data as a string.

        """
        try:
            from google.cloud import storage
        except ImportError:
            logger.warning("google-cloud-storage not available; install with: pip install google-cloud-storage")
            return
        path = self.__export_url.removeprefix("gs://")
        bucket, _, key = path.partition("/")
        try:
            client = storage.Client()
            client.bucket(bucket).blob(key).upload_from_string(body)
            logger.info("audit exported to gs://{}/{} ({} bytes)", bucket, key, len(body))
        except (OSError, ValueError, TypeError):
            logger.exception("audit GCS export failed")

    def save_jsonl(self, path: str, chunk_size: int = 1000) -> None:
        """Write the audit ledger to a JSONL file, streaming in chunks.

        Args:
            path: Destination file path.
            chunk_size: Records per chunk to avoid holding full ledger
                in memory.

        """
        with open(path, "w") as fh:
            batch: list[str] = []
            for record in self._ledger:
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
        self._ledger.clear()
        p = Path(path)
        if not p.exists():
            return
        corrupted: int = 0
        with open(p) as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if line:
                    try:
                        self._ledger.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        corrupted += 1
                        logger.warning("corrupted audit line {} in {}: {}", i, path, exc)
        self._event_index.clear()
        for r in self._ledger:
            et = r.get("event_type")
            if et:
                self._event_index.setdefault(et, []).append(r)
        if corrupted:
            logger.warning("audit load skipped {} corrupted line(s) from {}", corrupted, path)
