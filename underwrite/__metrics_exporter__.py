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
        self.__metrics: MetricsCollector = metrics
        self.__interval_seconds: float = interval_seconds
        self.__on_snapshot: Callable[[dict], None] | None = on_snapshot
        self.__stop_event: threading.Event = threading.Event()
        self.__thread: threading.Thread | None = None

    def start(self) -> None:
        if self.__thread is not None:
            return
        self.__stop_event = threading.Event()
        self.__thread = threading.Thread(
            target=self.__run, daemon=True, name="metrics-exporter"
        )
        self.__thread.start()

    def __run(self) -> None:
        while not self.__stop_event.is_set():
            self.__stop_event.wait(self.__interval_seconds)
            if self.__stop_event.is_set():
                break
            try:
                snap = self.__metrics.snapshot()
                if self.__on_snapshot is not None:
                    self.__on_snapshot(snap)
            except (OSError, ValueError, TypeError) as exc:
                logger.exception("metrics snapshot failed: {}", exc)

    def stop(self, timeout: float = 5.0) -> None:
        self.__stop_event.set()
        if self.__thread is not None:
            self.__thread.join(timeout=timeout)
            self.__thread = None
