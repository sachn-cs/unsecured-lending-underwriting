"""Periodic metrics export loop.

Lifecycle helper that runs a background thread snapshotting a
MetricsCollector at a configurable interval. Extracted from
Runtime so the composition root does not own thread management
and snapshotting logic.
"""

from __future__ import annotations

import threading
from typing import Callable

from underwrite.__logger__ import logger
from underwrite.__metrics__ import MetricsCollector


class MetricsExporter:
    """Periodically snapshots a MetricsCollector on a background thread.

    start() launches a daemon thread that calls snapshot() every
    *interval_seconds* and forwards the result to *on_snapshot*.
    stop() signals the thread to exit and joins it with a bounded
    timeout.

    Snapshots are forwarded via a callback (rather than a
    push-channel) so the exporter has no opinion about where the
    snapshot goes — Runtime can pipe to Prometheus, OTLP, or a
    log file by changing only the callback.
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        interval_seconds: float,
        on_snapshot: Callable[[dict], None] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self._metrics = metrics
        self._interval_seconds = interval_seconds
        self._on_snapshot = on_snapshot
        self._stop_event: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="metrics-exporter")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval_seconds)
            if self._stop_event.is_set():
                break
            try:
                snap = self._metrics.snapshot()
                if self._on_snapshot is not None:
                    self._on_snapshot(snap)
            except (OSError, ValueError, TypeError) as exc:
                logger.exception("metrics snapshot failed: {}", exc)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
