"""Abstract base class for every nano service.

Each service:
  - Has a unique service_id
  - Owns an Ed25519 Identity for signing its emitted events
  - Subscribes to events on a shared EventBus
  - Persists state through a Store
  - Implements handle(event) -> None to process incoming events
  - Emits events via emit(event_type, payload) which auto-signs
  - Tracks handler duration via distributed tracing
  - Supports saga orchestration for multi-step transactions
  - Guards against duplicate event processing via idempotency
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from underwrite.services.persistence import (
        BatchedStoreRepository,
        TypedStoreRepository,
    )

from underwrite.__authz__ import AccessControl, AuthzError
from underwrite.__bus__ import EventBus
from underwrite.__correlation__ import (
    correlation_context,
)
from underwrite.__correlation__ import (
    get_log_correlation_id as get_log_correlation_id,
)
from underwrite.__events__ import Event
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__logger__ import logger
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__store__ import Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.validate import PayloadValidator

MAX_EXECUTOR_QUEUE_FACTOR: int = 2


class EventEmitter:
    """Encapsulates the create/sign/publish sequence for outbound events.

    Pulled out of NanoService so the base class is not responsible for
    both subscribing to events and emitting them. Holds references to
    the bus, identity, metrics, tracer, and authz collaborator needed
    to construct, sign, authorise-publish, and instrument an event.
    """

    def __init__(
        self,
        service_id: str,
        identity: Identity,
        bus: EventBus,
        metrics: MetricsCollector | None,
        tracer: Tracer | None,
        authz: AccessControl | None,
    ) -> None:
        self.__service_id: str = service_id
        self.__identity: Identity = identity
        self.__bus: EventBus = bus
        self.__metrics: MetricsCollector | None = metrics
        self.__tracer: Tracer | None = tracer
        self.__authz: AccessControl | None = authz

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> Event:
        """Create, sign, authorise, publish and instrument an event.

        Args:
            event_type: The event type string.
            payload: Event payload dictionary.
            correlation_id: Optional correlation ID for tracing.

        Returns:
            The signed Event that was published.
        """
        if self.__authz:
            self.__authz.assert_publish(self.__service_id, event_type)
        trace_id: str = ""
        parent_span_id: str = ""
        if self.__tracer:
            trace_id = correlation_id or ""
        event: Event = Event(
            event_type=event_type,
            source=self.__service_id,
            source_key=self.__identity.public_key,
            payload=payload,
            correlation_id=correlation_id or "",
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        signed: Event = Event(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            source_key=event.source_key,
            timestamp=event.timestamp,
            payload=event.payload,
            correlation_id=event.correlation_id,
            trace_id=event.trace_id,
            parent_span_id=event.parent_span_id,
            signature=self.__identity.sign(event.canonical_sign_bytes().decode("utf-8")),
        )
        self.__bus.publish(signed)
        if self.__metrics:
            self.__metrics.increment(
                "events.emitted",
                {
                    "service": self.__service_id,
                    "event_type": event_type,
                },
            )
        return signed


class NanoService(ABC):
    """Base class that all nano services extend.

    Provides event emission/subscription, identity-based signing, state
    persistence, distributed tracing, saga orchestration, idempotency,
    metrics collection, health checks, and authz gating.
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
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
    ) -> None:
        """Initialize the nano service.

        Args:
            service_id: Unique identifier for this service instance.
            identity: Ed25519 identity for signing events. Created if omitted.
            bus: Event bus for pub/sub. Uses LocalBus if omitted.
            store: State persistence backend. Uses MemoryStore if omitted.
            metrics: Optional metrics collector for instrumentation.
            health: Optional health registry for liveness checks.
            authz: Optional access control for authorization gating.
            tracer: Optional distributed tracer for handler timing.
            saga: Optional saga orchestrator for multi-step transactions.
            supervisor: Optional supervisor for lifecycle management.
            secrets_manager: Optional SecretsManager. When provided, the
                service's Ed25519 private key is loaded from and persisted
                to the configured backend so the key survives restarts.
            max_concurrent: Max concurrent handler threads
                (0 = synchronous).
        """
        self.__service_id: str = service_id
        if identity is None:
            identity = Identity.create(service_id, secrets_manager=secrets_manager)
        self.__identity: Identity = identity
        if bus is None:
            raise ValueError(
                f"{type(self).__name__}({service_id!r}) requires bus; "
                "construct one with Runtime as the composition root."
            )
        if store is None:
            raise ValueError(
                f"{type(self).__name__}({service_id!r}) requires store; "
                "construct one with Runtime as the composition root."
            )
        self.__bus: EventBus = bus
        self.__store: Store = store
        self.__metrics: MetricsCollector | None = metrics
        self.__health: HealthRegistry | None = health
        self.__authz: AccessControl | None = authz
        self.__tracer: Tracer | None = tracer
        self.__saga: SagaOrchestrator | None = saga
        self.__supervisor: ServiceSupervisor | None = supervisor
        self.__secrets_manager: Any | None = secrets_manager
        self.__counter_lock: threading.Lock = threading.Lock()
        self.__subscriptions: list[str] = []
        self.__running: bool = False
        self.__events_handled: int = 0
        self.__events_failed: int = 0
        self.__last_event_time: float = 0.0
        self.__state_lock: threading.RLock = threading.RLock()
        self.__executor: concurrent.futures.ThreadPoolExecutor | None = (
            concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) if max_concurrent > 0 else None
        )

        self.__validator: PayloadValidator = PayloadValidator()

        if self.__authz is not None:
            self.__authz.trust(self.__service_id, self.__identity.public_key)

        if self.__saga:
            self.__saga.register_emitter(self.__service_id, self)

        self.__emitter: EventEmitter = EventEmitter(
            service_id=self.__service_id,
            identity=self.__identity,
            bus=self.__bus,
            metrics=self.__metrics,
            tracer=self.__tracer,
            authz=self.__authz,
        )

    @property
    def state_lock(self) -> threading.RLock:
        """Return the thread lock used for state mutation."""
        return self.__state_lock

    @property
    def service_id(self) -> str:
        """Return the unique identifier for this service instance."""
        return self.__service_id

    @property
    def bus(self) -> EventBus:
        """Return the event bus for this service."""
        return self.__bus

    @property
    def is_running(self) -> bool:
        """Return True if the service is currently processing events."""
        return self.__running

    @property
    def store(self) -> Store:
        """Return the state persistence backend for this service."""
        return self.__store

    @store.setter
    def store(self, value: Store) -> None:
        """Replace the state persistence backend.

        Provided primarily so tests can swap in a broken store to
        simulate I/O failures without monkey-patching the private
        attribute.
        """
        self.__store = value

    @property
    def metrics_collector(self) -> MetricsCollector | None:
        """Return the metrics collector for this service, or None if disabled."""
        return self.__metrics

    @property
    def validator(self) -> PayloadValidator:
        """Return the payload validator for extracting typed values from events."""
        return self.__validator

    def safe_store_get(self, key: str, default: Any = None) -> Any | None:
        """Get a value from the store, returning default on failure.

        Args:
            key: Store key to retrieve.
            default: Value returned when the key is missing or the read
                fails.

        Returns:
            The stored value, or *default* if the key is missing or an
            exception occurs.
        """
        try:
            return self.__store.get(key)
        except Exception:
            logger.exception("store get failed for {} in service {}", key, self.__service_id)
            return default

    def safe_store_set(self, key: str, value: Any) -> bool:
        """Write a value to the store, returning False on failure.

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
            logger.exception("store set failed for {} in service {}", key, self.__service_id)
            return False

    def subscribe(self, event_type: str) -> None:
        """Register this service to receive event_type events.

        Args:
            event_type: The event type string to subscribe to.
        """
        if self.__authz and not self.__authz.check_subscribe(self.__service_id, event_type):
            logger.warning("{} not authorized to subscribe to {}", self.__service_id, event_type)
            return
        sid: str = self.__bus.subscribe(event_type, self.__dispatch)
        self.__subscriptions.append(sid)

    def start(self) -> None:
        """Start event processing for this service."""
        self.__running = True

    def stop(self) -> None:
        """Stop event processing, shut down executor, and unsubscribe."""
        self.__running = False
        if self.__executor is not None:
            self.__executor.shutdown(wait=True)
            self.__executor = None
        for sid in self.__subscriptions:
            self.__bus.unsubscribe(sid)
        self.__subscriptions.clear()

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str = "",
    ) -> Event:
        """Create, sign, publish and return a new event.

        Args:
            event_type: The event type string.
            payload: Event payload dictionary.
            correlation_id: Optional correlation ID for tracing.

        Returns:
            The signed Event that was published.
        """
        return self.__emitter.emit(event_type, payload, correlation_id)

    def sign_event(self, payload: str) -> str:
        """Sign an arbitrary payload with this service's identity.

        Args:
            payload: The string payload to sign.

        Returns:
            The hex-encoded signature.
        """
        return self.__identity.sign(payload)

    def __dispatch(self, event: Event) -> None:
        """Internal: dispatch an event to the handler with authz and idempotency."""
        if not self.__running:
            return
        if self.__authz:
            try:
                self.__authz.assert_verified(event)
            except AuthzError:
                logger.warning(
                    "signature verification failed for {} from {}",
                    event.event_id,
                    event.source,
                )
                if self.__metrics:
                    self.__metrics.increment(
                        "authz.failures",
                        {
                            "service": self.__service_id,
                            "event_type": event.event_type,
                        },
                    )
                if hasattr(self.__bus, "dlq") and self.__bus.dlq:
                    self.__bus.dlq.put(event, "authz_failed", self.__service_id)
                return
        if self.__bus.idempotency.is_duplicate(self.__service_id, event.event_id):
            logger.debug("duplicate event {} dropped by {}", event.event_id, self.__service_id)
            if hasattr(self.__bus, "dlq") and self.__bus.dlq:
                self.__bus.dlq.put(event, "duplicate", self.__service_id)
            return
        if self.__executor is not None:
            worker_count = self.__executor._max_workers if hasattr(self.__executor, "_max_workers") else 0
            queue_size = self.__executor._work_queue.qsize() if hasattr(self.__executor, "_work_queue") else 0
            # Allow up to 2x worker count queued before dropping
            if worker_count > 0 and queue_size > worker_count * 2:
                logger.warning(
                    "{} executor queue full ({} queued, {} workers), dropping event {}",
                    self.__service_id,
                    queue_size,
                    worker_count,
                    event.event_id,
                )
                if hasattr(self.__bus, "dlq") and self.__bus.dlq:
                    self.__bus.dlq.put(event, "executor_queue_full", self.__service_id)
                return
            self.__executor.submit(self.__handle_event, event)
        else:
            self.__handle_event(event)

    def __handle_event(self, event: Event) -> None:
        """Internal: process a single event with tracing and metrics."""
        start = time.perf_counter()
        context = (
            self.__tracer.trace(
                f"handle.{event.event_type}",
                trace_id=event.trace_id or event.correlation_id or event.event_id,
                parent_span_id=event.parent_span_id,
                tags={"service": self.__service_id, "event_type": event.event_type},
            )
            if self.__tracer
            else contextlib.nullcontext()
        )
        with context:
            try:
                old_cid = correlation_context.get()
                correlation_context.set(event.correlation_id or "")
                try:
                    self.handle(event)
                finally:
                    correlation_context.set(old_cid)
                with self.__counter_lock:
                    self.__events_handled += 1
                    self.__last_event_time = start
                if self.__supervisor:
                    self.__supervisor.record_success(self.__service_id)
                if self.__metrics:
                    elapsed = (time.perf_counter() - start) * 1000.0
                    self.__metrics.timer(
                        "handle.duration",
                        elapsed,
                        {
                            "service": self.__service_id,
                            "event_type": event.event_type,
                        },
                    )
                    self.__metrics.increment(
                        "events.handled",
                        {
                            "service": self.__service_id,
                            "event_type": event.event_type,
                        },
                    )
            except Exception:
                with self.__counter_lock:
                    self.__events_failed += 1
                if self.__supervisor:
                    self.__supervisor.record_failure(self.__service_id)
                logger.exception(
                    "handler {} failed processing {}",
                    self.__service_id,
                    event.event_type,
                )
                if self.__metrics:
                    self.__metrics.increment(
                        "events.failed",
                        {
                            "service": self.__service_id,
                            "event_type": event.event_type,
                        },
                    )

    @abstractmethod
    def handle(self, event: Event) -> None:
        """Process an incoming event. Override in subclasses.

        Args:
            event: The incoming Event to process.
        """

    def health_check(self) -> dict[str, Any]:
        """Health check for this service. Override for service-specific checks.

        Returns:
            Dict with keys: ok, service_id, events_handled, events_failed,
            last_event_time.
        """
        with self.__counter_lock:
            return {
                "ok": self.__running,
                "service_id": self.__service_id,
                "events_handled": self.__events_handled,
                "events_failed": self.__events_failed,
                "last_event_time": self.__last_event_time,
            }


class StatefulService(NanoService, ABC):
    """Base class for nano services that hold mutable in-memory state.

    Provides a shared reentrant lock (self.state_lock) and factory
    helpers for creating StoreRepository instances bound to the
    service's store.

    Typical usage:
        class MyService(StatefulService):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.data: dict[str, Any] = {}
                self.repo = self.store_repo('data', dict)
                loaded = self.repo.load(default={})
                if loaded:
                    self.data = loaded
    """

    def store_repo(
        self,
        suffix: str,
        expected_type: type | tuple[type, ...] = object,
    ) -> TypedStoreRepository:
        """Create a TypedStoreRepository for suffix under this service's ID.

        The store key is f'{self.service_id}:{suffix}'.

        Args:
            suffix: Key suffix (e.g. 'collateral' -> key
                'collateral:collateral').
            expected_type: Type constraint for loaded values.

        Returns:
            A new TypedStoreRepository bound to this service's store.
        """
        from underwrite.services.persistence import TypedStoreRepository

        return TypedStoreRepository(
            store=self.store,
            key=f"{self.service_id}:{suffix}",
            expected_type=expected_type,
        )

    def batched_repo(
        self,
        suffix: str,
        expected_type: type | tuple[type, ...] = object,
        sync_interval: int = 10,
    ) -> BatchedStoreRepository:
        """Create a BatchedStoreRepository for suffix under this service's ID.

        Args:
            suffix: Key suffix.
            expected_type: Type constraint for loaded values.
            sync_interval: Persist only every N incr_and_maybe_sync()
                calls.

        Returns:
            A new BatchedStoreRepository.
        """
        from underwrite.services.persistence import BatchedStoreRepository

        return BatchedStoreRepository(
            store=self.store,
            key=f"{self.service_id}:{suffix}",
            expected_type=expected_type,
            sync_interval=sync_interval,
        )
