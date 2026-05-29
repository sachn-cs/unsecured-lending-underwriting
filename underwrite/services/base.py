"""Abstract base class for every nano service.

Each service:
  - Has a unique ``service_id``
  - Owns an Ed25519 ``Identity`` for signing its emitted events
  - Subscribes to events on a shared ``EventBus``
  - Persists state through a ``Store``
  - Implements ``handle(event) -> None`` to process incoming events
  - Emits events via ``emit(event_type, payload)`` which auto-signs
  - Tracks handler duration via distributed tracing
  - Supports saga orchestration for multi-step transactions
  - Guards against duplicate event processing via idempotency
"""

from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from underwrite.__authz__ import AccessControl, AuthzError
from underwrite.__bus__ import EventBus, LocalBus
from underwrite.__events__ import Event
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import MemoryStore, Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Span, Tracer

logger = logging.getLogger(__name__)

_log_context = threading.local()


def get_log_correlation_id() -> str:
    """Returns the correlation_id for the current thread, or empty string."""
    return getattr(_log_context, "correlation_id", "")


class BatchPersistenceMixin:
    """Mixin for services that want to batch persistence to reduce O(n) serialization.

    Instead of writing to the store on every event, accumulates a counter
    and only triggers the actual sync every *sync_interval* calls.
    Subclasses must implement ``_do_sync_store()`` to perform the actual write.
    """

    def __init__(self, sync_interval: int = 10) -> None:
        self.__batch_lock: threading.Lock = threading.Lock()
        self.__sync_interval: int = max(sync_interval, 1)
        self.__sync_counter: int = 0

    def _incr_and_maybe_sync(self) -> bool:
        """Increments the counter and triggers sync if threshold reached.

        Returns:
            True if a sync was triggered, False otherwise.
        """
        with self.__batch_lock:
            self.__sync_counter += 1
            if self.__sync_counter >= self.__sync_interval:
                self.__sync_counter = 0
            else:
                return False
        self._do_sync_store()
        return True

    def _force_sync(self) -> None:
        """Immediately triggers a sync regardless of the counter."""
        with self.__batch_lock:
            self.__sync_counter = 0
        self._do_sync_store()

    def _reset_counter(self) -> None:
        with self.__batch_lock:
            self.__sync_counter = 0

    @abstractmethod
    def _do_sync_store(self) -> None:
        """Subclasses must implement this to perform the actual store write."""


class NanoService(ABC):
    """Base class that all nano services extend.

    Provides event emission/subscription, identity-based signing,
    state persistence, distributed tracing, saga orchestration,
    idempotency, metrics collection, health checks, and authz gating.
    """

    def __init__(
        self,
        service_id: str,
        identity: Identity | None = None,
        bus: EventBus | None = None,
        store: Store | None = None,
        metrics: MetricsCollector | None = None,
        health: HealthRegistry | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: SagaOrchestrator | None = None,
        supervisor: ServiceSupervisor | None = None,
    ) -> None:
        """Initialise the nano service.

        Args:
            service_id: Unique identifier for this service instance.
            identity: Ed25519 identity for signing events. Created if omitted.
            bus: Event bus for pub/sub. Uses LocalBus if omitted.
            store: State persistence backend. Uses MemoryStore if omitted.
            metrics: Optional metrics collector for instrumentation.
            health: Optional health registry for liveness checks.
            authz: Optional access control for authz gating.
            tracer: Optional distributed tracer for handler timing.
            saga: Optional saga orchestrator for multi-step transactions.
        """
        self.__service_id: str = service_id
        self.__identity: Identity = identity or Identity.create(service_id)
        self.__bus: EventBus = bus or LocalBus()
        self.__store: Store = store or MemoryStore()
        self.__metrics: MetricsCollector | None = metrics
        self.__health: HealthRegistry | None = health
        self.__authz: AccessControl | None = authz
        self.__tracer: Tracer | None = tracer
        self.__saga: SagaOrchestrator | None = saga
        self.__supervisor: ServiceSupervisor | None = supervisor
        self.__counter_lock: threading.Lock = threading.Lock()
        self.__subscriptions: list[str] = []
        self.__running: bool = False
        self.__events_handled: int = 0
        self.__events_failed: int = 0
        self.__last_event_time: float = 0.0

        if self.__saga:
            self.__saga.register_emitter(self.__service_id, self)

    @property
    def service_id(self) -> str:
        """Return the unique identifier for this service instance."""
        return self.__service_id

    @property
    def is_running(self) -> bool:
        """Return True if the service is currently processing events."""
        return self.__running

    @property
    def store(self) -> Store:
        """Return the state persistence backend for this service."""
        return self.__store

    @property
    def metrics_collector(self) -> MetricsCollector | None:
        """Return the metrics collector for this service, or None if disabled."""
        return self.__metrics

    def safe_store_get(self, key: str, default: Any = None) -> Any | None:
        """Get a value from the store, logging and returning *default* on failure.

        Args:
            key: Store key to retrieve.
            default: Value returned when the key is missing or the read fails.

        Returns:
            The stored value, *default* if the key is missing, or *default*
            if the read raises an exception.
        """
        try:
            return self.__store.get(key)
        except Exception:
            logger.exception("store get failed for %s in service %s", key,
                             self.__service_id)
            return default

    def safe_store_set(self, key: str, value: Any) -> bool:
        """Write a value to the store, logging and returning False on failure.

        Args:
            key: Store key for the value.
            value: Value to persist.

        Returns:
            True if the write succeeded, False otherwise.
        """
        try:
            self.__store.set(key, value)
            return True
        except Exception:
            logger.exception("store set failed for %s in service %s", key,
                             self.__service_id)
            return False

    def subscribe(self, event_type: str) -> None:
        """Registers this service to receive *event_type* events."""
        if self.__authz and not self.__authz.check_subscribe(
                self.__service_id, event_type):
            logger.warning("%s not authorized to subscribe to %s",
                           self.__service_id, event_type)
            return
        sid: str = self.__bus.subscribe(event_type, self.__dispatch)
        self.__subscriptions.append(sid)

    def start(self) -> None:
        """Starts event processing for this service."""
        self.__running = True

    def stop(self) -> None:
        """Stops event processing and unsubscribes from the bus."""
        self.__running = False
        for sid in self.__subscriptions:
            self.__bus.unsubscribe(sid)
        self.__subscriptions.clear()

    def emit(self,
             event_type: str,
             payload: dict[str, Any],
             correlation_id: str = "") -> Event:
        """Creates, signs, publishes and returns a new event."""
        event: Event = Event(
            event_type=event_type,
            source=self.__service_id,
            source_key=self.__identity.public_key,
            payload=payload,
            correlation_id=correlation_id or "",
        )
        payload_str: str = json.dumps(payload, sort_keys=True, default=str)
        to_sign: str = f"{event.event_id}:{event.timestamp}:{event.event_type}:{payload_str}"
        signed: Event = Event(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            source_key=event.source_key,
            timestamp=event.timestamp,
            payload=event.payload,
            correlation_id=event.correlation_id,
            signature=self.__identity.sign(to_sign),
        )
        if self.__authz:
            self.__authz.assert_publish(self.__service_id, event_type)
            self.__authz.trust(self.__service_id, self.__identity.public_key)
        self.__bus.publish(signed)
        if self.__metrics:
            self.__metrics.increment("events.emitted", {
                "service": self.__service_id,
                "event_type": event_type,
            })
        return signed

    def sign_event(self, payload: str) -> str:
        """Signs an arbitrary payload with this service's identity."""
        return self.__identity.sign(payload)

    def __dispatch(self, event: Event) -> None:
        if not self.__running:
            return
        if self.__authz:
            try:
                self.__authz.assert_verified(event)
            except AuthzError:
                logger.warning("signature verification failed for %s from %s",
                               event.event_id, event.source)
                if self.__metrics:
                    self.__metrics.increment(
                        "authz.failures", {
                            "service": self.__service_id,
                            "event_type": event.event_type,
                        })
                return
        if self.__bus.idempotency.is_duplicate(self.__service_id,
                                               event.event_id):
            logger.debug("duplicate event %s dropped by %s", event.event_id,
                         self.__service_id)
            return
        start = time.perf_counter()
        span: Span | None = None
        if self.__tracer:
            span = self.__tracer.start_span(
                f"handle.{event.event_type}",
                trace_id=event.correlation_id or event.event_id,
                tags={
                    "service": self.__service_id,
                    "event_type": event.event_type
                },
            )
        try:
            _log_context.correlation_id = event.correlation_id or ""
            self.handle(event)
            with self.__counter_lock:
                self.__events_handled += 1
                self.__last_event_time = start
            if self.__supervisor:
                self.__supervisor.record_success(self.__service_id)
            if self.__metrics:
                elapsed = (time.perf_counter() - start) * 1000.0
                self.__metrics.timer("handle.duration", elapsed, {
                    "service": self.__service_id,
                    "event_type": event.event_type,
                })
                self.__metrics.increment("events.handled", {
                    "service": self.__service_id,
                    "event_type": event.event_type,
                })
        except Exception:
            with self.__counter_lock:
                self.__events_failed += 1
            if self.__supervisor:
                self.__supervisor.record_failure(self.__service_id)
            logger.exception("handler %s failed processing %s",
                             self.__service_id, event.event_type)
            if self.__metrics:
                self.__metrics.increment("events.failed", {
                    "service": self.__service_id,
                    "event_type": event.event_type,
                })
            raise
        finally:
            if span is not None and self.__tracer is not None:
                self.__tracer.end_span(span)

    @abstractmethod
    def handle(self, event: Event) -> None:
        """Process an incoming event.  Override in subclasses."""

    def health_check(self) -> dict[str, Any]:
        """Health check for this service.  Override to add service-specific checks."""
        with self.__counter_lock:
            return {
                "ok": self.__running,
                "service_id": self.__service_id,
                "events_handled": self.__events_handled,
                "events_failed": self.__events_failed,
                "last_event_time": self.__last_event_time,
            }
