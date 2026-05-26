"""Service registry — discovers, activates, and manages all nano services.

Usage:
    from underwrite.runtime import Runtime

    runtime = Runtime(config)
    runtime.start(["mechanism", "audit"])
    runtime.stop()
"""

from __future__ import annotations

__all__ = [
    "Runtime",
]

import importlib
import logging
import threading
from pathlib import Path
from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus, LocalBus
from underwrite.__config__ import Configuration
from underwrite.__events__ import Event
from underwrite.__exceptions__ import ServiceNotFoundError
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__metrics__ import MetricsCollector
from underwrite.__migrate__ import default_plan
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__secrets__ import SecretsManager
from underwrite.__store__ import FileStore, MemoryStore, Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite._service_registry import SERVICE_CLASSES, SERVICE_MAP, WIRING
from underwrite.services import NanoService

logger = logging.getLogger(__name__)


class Runtime:
    """Manages lifecycle of all nano services with health, metrics, authz, migration, tracing, and saga."""

    def __init__(self, config: Configuration | None = None,
                 readonly: bool = False) -> None:
        """Initialises the Runtime.

        Args:
            config: Runtime configuration. Loaded from defaults if omitted.
            readonly: If ``True``, skip side-effecting initialisation
                (migrations, metrics export, saga loading, supervisor,
                tracer, authz).  Intended for CLI commands that only
                read state.
        """
        self.__config: Configuration = config or Configuration.load()
        Configuration._validate(self.__config.to_dict())
        self.__configure_logging()
        self.__store: Store = self.__build_store()
        self.__read_store: Store | None = self.__build_read_store()
        self.__services: dict[str, NanoService] = {}
        if readonly:
            self.__bus = LocalBus(store=self.__store)
            self.__health = HealthRegistry()
            self.__tracer = None
            self.__secrets = None
            self.__saga = None
            self.__metrics = None
            self.__authz = None
            self.__supervisor = None
            self.__metrics_thread = None
            self.__metrics_stop = None
            self.__register_subsystem_health()
            return
        self.__tracer: Tracer | None = self.__build_tracer()
        self.__bus: EventBus = self.__build_bus()
        self.__secrets: SecretsManager | None = self.__build_secrets()
        self.__saga: SagaOrchestrator | None = (
            SagaOrchestrator(store=self.__store)
            if self.__config.saga.enabled else None
        )
        self.__health: HealthRegistry = HealthRegistry()
        self.__metrics: MetricsCollector | None = MetricsCollector(
        ) if self.__config.metrics.enabled else None
        self.__authz: AccessControl | None = self.__build_authz()
        self.__supervisor: ServiceSupervisor | None = self.__build_supervisor()
        self.__metrics_thread: threading.Thread | None = None
        self.__metrics_stop: threading.Event | None = None

        self.__register_subsystem_health()
        self.__run_migrations()
        self.__start_metrics_export()

    def __configure_logging(self) -> None:
        import json as _json
        import logging as _logging

        cfg = self.__config.logging
        level = getattr(_logging, cfg.level.upper(), _logging.INFO)
        handler: _logging.Handler
        if cfg.output == "stdout":
            handler = _logging.StreamHandler()
        elif cfg.output == "stderr":
            handler = _logging.StreamHandler()
        else:
            handler = _logging.StreamHandler()
        handler.setLevel(level)

        if cfg.log_format == "json":

            class _JsonFormatter(_logging.Formatter):

                def format(self, record: _logging.LogRecord) -> str:
                    data: dict[str, object] = {
                        "timestamp": self.formatTime(record),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                        "module": record.module,
                        "line": record.lineno,
                    }
                    corr_id = getattr(record, "correlation_id", None)
                    if corr_id:
                        data["correlation_id"] = corr_id
                    return _json.dumps(data)

            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(
                _logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(correlation_id)s %(name)s: %(message)s"))

        root = _logging.getLogger("underwrite")

        class _CorrelationFilter(_logging.Filter):

            def filter(self, record: _logging.LogRecord) -> bool:
                if not hasattr(record, "correlation_id"):
                    from underwrite.services.base import get_log_correlation_id
                    record.correlation_id = get_log_correlation_id()  # type: ignore[attr-defined]
                return True

        root.addFilter(_CorrelationFilter())
        root.setLevel(level)
        root.addHandler(handler)

    def __build_secrets(self) -> SecretsManager | None:
        cfg = self.__config.secrets
        if cfg.backend == "none":
            return None
        return SecretsManager(config=cfg)

    def __build_supervisor(self) -> ServiceSupervisor | None:
        cfg = self.__config.recovery
        if not cfg.auto_restart:
            return None
        return ServiceSupervisor(
            max_restarts=cfg.max_restarts,
            backoff_seconds=cfg.backoff_seconds,
        )

    def __build_tracer(self) -> Tracer | None:
        if not self.__config.tracing.enabled:
            return None
        exporter: Any = None
        if self.__config.tracing.exporter == "console":
            from underwrite.__tracer__ import ConsoleSpanExporter
            exporter = ConsoleSpanExporter()
        elif self.__config.tracing.exporter == "otlp":
            from underwrite.__tracer__ import OtlpSpanExporter
            exporter = OtlpSpanExporter(service_name="underwrite")
        return Tracer(service_id="runtime", exporter=exporter)

    def __build_bus(self) -> EventBus:
        return LocalBus(
            rate_limit=self.__config.bus.rate_limit,
            max_workers=self.__config.bus.max_workers,
            max_futures=self.__config.bus.max_futures,
            store=self.__store,
        )

    def __build_store(self) -> Store:
        cfg = self.__config.store
        if cfg.backend == "filesystem":
            return FileStore(self.__config.data_dir)
        elif cfg.backend == "memory":
            return MemoryStore()
        elif cfg.backend == "postgres":
            from underwrite.__store__ import PostgresStore
            return PostgresStore(dsn=cfg.dsn, pool_size=cfg.pool_size)
        logger.warning(
            "unrecognized store backend %r, falling back to FileStore",
            cfg.backend)
        return FileStore(self.__config.data_dir)

    def __build_read_store(self) -> Store | None:
        cfg = self.__config.store
        if not cfg.read_backend:
            return None
        if cfg.read_backend == "filesystem":
            from underwrite.__store__ import FileStore
            return FileStore(self.__config.data_dir)
        elif cfg.read_backend == "postgres":
            from underwrite.__store__ import PostgresStore
            return PostgresStore(dsn=cfg.read_dsn or cfg.dsn,
                                 pool_size=cfg.pool_size)
        if cfg.read_backend != "memory":
            logger.warning(
                "unrecognized read store backend %r, falling back to MemoryStore",
                cfg.read_backend)
        return MemoryStore()

    def __build_authz(self) -> AccessControl | None:
        if not self.__config.authz.enabled:
            return None
        acl = AccessControl()
        policy_file = self.__config.authz.policy_file
        if policy_file:
            import json as json_mod
            p = Path(policy_file)
            if p.exists():
                try:
                    with open(p) as fh:
                        rules = json_mod.load(fh)
                except (json_mod.JSONDecodeError, OSError) as exc:
                    logger.error("failed to load authz policy file %s: %s", policy_file, exc)
                    return None
                for rule in rules.get("allow", []):
                    acl.allow(rule.get("subject", "*"),
                              rule.get("resource", "*"))
                for rule in rules.get("deny", []):
                    acl.deny(rule.get("subject", "*"),
                             rule.get("resource", "*"))
        return acl

    def __start_metrics_export(self) -> None:
        if not self.__metrics or self.__config.metrics.export_interval <= 0:
            return
        if self.__config.tracing.exporter != "otlp":
            return
        stop_event = threading.Event()
        self.__metrics_stop = stop_event
        metrics: MetricsCollector = self.__metrics
        interval: int = self.__config.metrics.export_interval

        def _export_loop() -> None:
            while not stop_event.is_set():
                stop_event.wait(interval)
                if stop_event.is_set():
                    break
                try:
                    snap = metrics.snapshot()
                    if not any([snap.get("counters"),
                                snap.get("timers"),
                                snap.get("gauges")]):
                        continue
                    _logger = logging.getLogger("underwrite.metrics")
                    _logger.debug("exporting %d counters, %d timers, %d gauges",
                                  len(snap.get("counters", {})),
                                  len(snap.get("timers", {})),
                                  len(snap.get("gauges", {})))
                except Exception:
                    logger.exception("metrics export failed")

        self.__metrics_thread = threading.Thread(
            target=_export_loop, daemon=True, name="metrics-export")
        self.__metrics_thread.start()

    def __register_subsystem_health(self) -> None:
        self.__health.register("bus", lambda: {"ok": True})
        self.__health.register("store", lambda: self.__store.health())
        read_store = self.__read_store
        if read_store is not None:
            self.__health.register("read_store",
                                   lambda: read_store.health())
        self.__health.register(
            "services", lambda: {
                "ok":
                    True,
                "running": [
                    sid for sid, svc in self.__services.items()
                    if svc.is_running
                ],
            })
        if self.__metrics:
            self.__health.register("metrics", lambda: {"ok": True})
        tracer = self.__tracer
        if tracer is not None:
            self.__health.register(
                "tracer", lambda: {
                    "ok": True,
                    "spans": len(tracer.spans)
                })
        if self.__saga:
            self.__health.register("saga", lambda: {"ok": True})
        if hasattr(self.__bus, "dlq") and self.__bus.dlq:
            self.__health.register(
                "dlq", lambda: {
                    "ok": True,
                    "dead_letter_count": self.__bus.dlq.count,
                })
        if self.__supervisor:
            sup = self.__supervisor
            self.__health.register("supervisor", lambda: sup.health())

    def __run_migrations(self) -> None:
        if self.__config.migration.auto_migrate:
            plan = default_plan()
            self.__store.migrate(plan)

    @property
    def bus(self) -> EventBus:
        """Returns the event bus instance."""
        return self.__bus

    @property
    def store(self) -> Store:
        """Returns the primary store instance."""
        return self.__store

    @property
    def services(self) -> dict[str, NanoService]:
        """Returns a snapshot of registered services keyed by name."""
        return dict(self.__services)

    @property
    def health(self) -> HealthRegistry:
        """Returns the health check registry."""
        return self.__health

    @property
    def metrics(self) -> MetricsCollector | None:
        """Returns the metrics collector, or ``None`` if disabled."""
        return self.__metrics

    @property
    def authz(self) -> AccessControl | None:
        """Returns the access control instance, or ``None`` if disabled."""
        return self.__authz

    @property
    def tracer(self) -> Tracer | None:
        """Returns the tracer, or ``None`` if tracing is disabled."""
        return self.__tracer

    @property
    def saga(self) -> SagaOrchestrator | None:
        """Returns the saga orchestrator, or ``None`` if sagas are disabled."""
        return self.__saga

    @property
    def supervisor(self) -> ServiceSupervisor | None:
        """Returns the service supervisor, or ``None`` if auto-recovery is disabled."""
        return self.__supervisor

    @property
    def secrets(self) -> SecretsManager | None:
        """Returns the secrets manager, or ``None`` if secrets are disabled."""
        return self.__secrets

    def register(self,
                 service_name: str,
                 identity: Identity | None = None) -> NanoService:
        """Instantiates a nano service by name and registers it."""
        module_path = SERVICE_MAP.get(service_name)
        if not module_path:
            raise ServiceNotFoundError(f"unknown service: {service_name}")
        class_name = SERVICE_CLASSES.get(service_name)
        if not class_name:
            raise ServiceNotFoundError(
                f"no class mapping for service: {service_name}")
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name, None)
        if cls is None or not (isinstance(cls, type) and
                               issubclass(cls, NanoService)):
            raise ServiceNotFoundError(
                f"class {class_name} not found in {module_path}")
        extra: dict[str, Any] = {}
        if service_name == "fee":
            extra["fee_schedules"] = dict(self.__config.fee.schedules)
        elif service_name == "governance":
            extra["param_ranges"] = {
                k: list(v) for k, v in self.__config.governance.param_ranges.items()
            }
            extra["param_defaults"] = dict(self.__config.governance.param_defaults)
        elif service_name == "audit":
            extra["max_ledger"] = self.__config.audit.max_ledger
            extra["export_url"] = self.__config.audit.export_url
        svc = cls(
            service_id=service_name,
            identity=identity,
            bus=self.__bus,
            store=self.__store,
            metrics=self.__metrics,
            health=self.__health,
            authz=self.__authz,
            tracer=self.__tracer,
            saga=self.__saga,
            supervisor=self.__supervisor,
            **extra,
        )
        self.__services[service_name] = svc
        if self.__health:
            svc_id = service_name
            self.__health.register(f"service:{svc_id}", svc.health_check)
        return svc

    def wire(self, service_name: str) -> None:
        """Subscribes a service to all event types it cares about."""
        svc = self.__services.get(service_name)
        if not svc:
            logger.warning("wire called for unregistered service %s",
                           service_name)
            return
        for event_type, subscribers in WIRING.items():
            if service_name in subscribers:
                svc.subscribe(event_type)
        svc.subscribe(service_name)

    def start(self, service_names: list[str] | None = None) -> None:
        """Starts the event bus and selected services.

        Args:
            service_names: List of services to start.  If ``None``,
                starts only the services enabled in configuration.
        """
        if service_names is None:
            service_names = self.__config.enabled_services()
        for name in service_names:
            if name not in self.__services:
                self.register(name)
            self.wire(name)
            self.__services[name].start()
        self.__bus.start()

    def stop(self) -> None:
        """Stops all services, the metrics export loop, and the event bus."""
        if self.__metrics_stop:
            self.__metrics_stop.set()
        if self.__metrics_thread and self.__metrics_thread.is_alive():
            self.__metrics_thread.join(timeout=5.0)
        for svc in self.__services.values():
            svc.stop()
        self.__bus.stop()
        self.__store.shutdown()
        if self.__read_store is not None:
            self.__read_store.shutdown()

    def get(self, service_name: str) -> NanoService | None:
        """Returns a registered service by name, or ``None``."""
        return self.__services.get(service_name)

    def publish(self,
                event_type: str,
                payload: dict[str, Any],
                correlation_id: str = "") -> str:
        """Publishes an event directly to the bus (used for external input)."""
        event = Event(
            event_type=event_type,
            source="runtime",
            source_key="",
            payload=payload,
            correlation_id=correlation_id or "",
        )
        return self.__bus.publish(event)

    async def async_publish(self,
                            event_type: str,
                            payload: dict[str, Any],
                            correlation_id: str = "") -> str:
        """Async variant of ``publish`` for use in async contexts (e.g. FastAPI).

        Dispatches the synchronous publish to a thread pool to avoid
        blocking the async event loop.
        """
        import asyncio
        return await asyncio.to_thread(
            self.publish, event_type, payload, correlation_id)

    def replay_saga(self, saga_id: str) -> bool:
        """Replays an incomplete saga for crash recovery.

        Delegates to ``SagaOrchestrator.replay_saga``.
        """
        if self.__saga is None:
            logger.warning("replay_saga: sagas are disabled")
            return False
        return self.__saga.replay_saga(saga_id)
