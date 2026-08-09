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

import dataclasses
import importlib
import re
import sys
import threading
from pathlib import Path
from typing import Any

from underwrite.__authz__ import AccessControl
from underwrite.__bus__ import EventBus, LocalBus
from underwrite.__config__ import Configuration
from underwrite.__events__ import Event
from underwrite.__exceptions__ import ServiceNotFoundError
from underwrite.__handler_registry__ import HANDLER_CLASSES, HANDLER_MAP, WIRING
from underwrite.__health__ import HealthRegistry
from underwrite.__identity__ import Identity
from underwrite.__logger__ import JsonFormatter, TextFormatter, logger, loguru_sink_format
from underwrite.__metrics__ import MetricsCollector
from underwrite.__metrics_exporter__ import MetricsExporter
from underwrite.__migrate__ import default_plan
from underwrite.__saga__ import SagaOrchestrator
from underwrite.__secrets__ import SecretsManager
from underwrite.__store__ import FileStore, MemoryStore, Store
from underwrite.__supervisor__ import ServiceSupervisor
from underwrite.__tracer__ import Tracer
from underwrite.services import NanoService
from underwrite.services.kyc_providers.base import KycProvider

_VALID_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_.-]+$")


def build_authz(authz_config: Any) -> AccessControl | None:
    """Build an AccessControl from AuthzConfig. Extracted so tests
    can exercise the policy-loading code without needing a full
    Runtime instance.
    """
    if not authz_config.enabled:
        return None
    acl = AccessControl()
    policy_file = authz_config.policy_file
    if policy_file:
        import json as json_mod

        p = Path(policy_file)
        if p.exists():
            try:
                with open(p) as fh:
                    rules = json_mod.load(fh)
            except (json_mod.JSONDecodeError, OSError) as exc:
                logger.error("failed to load authz policy file {}: {}", policy_file, exc)
                return None
            for rule in rules.get("allow", []):
                acl.allow(rule.get("subject", "*"), rule.get("resource", "*"))
            for rule in rules.get("deny", []):
                acl.deny(rule.get("subject", "*"), rule.get("resource", "*"))
    else:
        acl.allow("*", "*")
    return acl


def build_event_bus(bus_config: Any, store: Store) -> EventBus:
    """Construct the configured EventBus backend.

    Extracted from Runtime so the bus selection logic is testable
    without standing up the full Runtime composition root.
    """
    backend = bus_config.backend
    if backend == "sqs":
        from underwrite.__bus_sqs__ import SqsBus

        return SqsBus(
            queue_url=bus_config.sqs_queue_url,
            region=bus_config.sqs_region,
            store=store,
        )
    if backend == "modal":
        from underwrite.__bus_modal__ import ModalBus

        return ModalBus(
            queue_name=bus_config.modal_queue_name,
            store=store,
        )
    return LocalBus(
        rate_limit=bus_config.rate_limit,
        max_workers=bus_config.max_workers,
        max_futures=bus_config.max_futures,
        store=store,
    )


class Runtime:
    """Manages lifecycle of all nano services with health, metrics, authz, migration, tracing, and saga."""

    __store: Store
    __read_store: Store | None
    __services: dict[str, NanoService]
    __bus: EventBus
    __health: HealthRegistry
    __tracer: Tracer | None
    __secrets: SecretsManager | None
    __saga: SagaOrchestrator | None
    __metrics: MetricsCollector | None
    __authz: AccessControl | None
    __supervisor: ServiceSupervisor | None
    __metrics_exporter: MetricsExporter | None
    __runtime_identity: Identity | None
    __publisher_identities: dict[str, Identity]
    __publisher_lock: threading.Lock

    def __init__(self, config: Configuration | None = None, readonly: bool = False) -> None:
        """Initializes the Runtime.

        Args:
            config: Runtime configuration. Loaded from defaults if omitted.
            readonly: If ``True``, skip side-effecting initialisation
                (migrations, metrics export, saga loading, supervisor,
                tracer, authz).  Intended for CLI commands that only
                read state.
        """
        self.__config: Configuration = config or Configuration.load()
        self.__configure_logging()
        self.__store = self.__build_store()
        self.__read_store = self.__build_read_store()
        self.__services = {}
        self.__lock: threading.RLock = threading.RLock()
        self.__runtime_identity = None
        self.__publisher_identities = {}
        self.__publisher_lock = threading.Lock()
        if readonly:
            self.__bus = LocalBus(store=self.__store)
            self.__health = HealthRegistry()
            self.__tracer = None
            self.__secrets = None
            self.__saga = None
            self.__metrics = None
            self.__authz = None
            self.__supervisor = None
            self.__metrics_exporter = None
            self.__register_subsystem_health()
            return
        self.__runtime_identity = None
        self.__secrets = self.__build_secrets()
        self.__runtime_identity = Identity.create("runtime", secrets_manager=self.__secrets)
        self.__kyc_providers: dict[str, KycProvider] = self.__build_kyc_providers()
        self.__tracer: Tracer | None = self.__build_tracer()
        self.__bus = self.__build_bus()
        self.__saga = SagaOrchestrator(store=self.__store) if self.__config.saga.enabled else None
        self.__health = HealthRegistry()
        self.__metrics = MetricsCollector() if self.__config.metrics.enabled else None
        self.__authz = self.__build_authz()
        if self.__authz is not None and self.__runtime_identity is not None:
            self.__authz.trust(self.__runtime_identity.service_id, self.__runtime_identity.public_key)
        self.__supervisor = self.__build_supervisor()
        self.__metrics_exporter = None

        self.__register_subsystem_health()

    def __configure_logging(self) -> None:
        cfg = self.__config.logging
        sink = sys.stdout if cfg.output == "stdout" else sys.stderr
        formatter = JsonFormatter() if cfg.log_format == "json" else TextFormatter()
        logger.remove()
        logger.add(sink, level=cfg.level, format=loguru_sink_format(formatter), colorize=False)

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

    def __build_kyc_providers(self) -> dict[str, KycProvider]:
        """Resolve the configured KYC provider clients.

        Returns a dict mapping the provider name (``pan`` /
        ``aadhaar`` / ``cibil`` / ``ckyc``) to the configured
        client instance. When ``kyc_providers`` is not in the
        configuration, returns an empty dict; the compliance and
        credit_bureau services then fall back to format-only
        validation.
        """
        kp = getattr(self.__config, "kyc_providers", None)
        if kp is None:
            return {}
        return kp.all(self.__secrets)

    def __build_tracer(self) -> Tracer | None:
        if not self.__config.tracing.enabled:
            return None
        from underwrite.__tracer__ import ConsoleSpanExporter, OtlpSpanExporter, SpanExporter

        exporter: SpanExporter | None = None
        if self.__config.tracing.exporter == "console":
            exporter = ConsoleSpanExporter()
        elif self.__config.tracing.exporter == "otlp":
            exporter = OtlpSpanExporter(service_name="underwrite")
        return Tracer(service_id="runtime", exporter=exporter)

    def __build_bus(self) -> EventBus:
        return build_event_bus(self.__config.bus, self.__store)

    def __build_store(self) -> Store:
        cfg = self.__config.store
        if cfg.backend == "filesystem":
            return FileStore(self.__config.data_dir)
        elif cfg.backend == "memory":
            return MemoryStore()
        elif cfg.backend == "postgres":
            from underwrite.__store__ import PostgresStore

            return PostgresStore(dsn=cfg.dsn, pool_size=cfg.pool_size)
        logger.warning("unrecognized store backend {!r}, falling back to FileStore", cfg.backend)
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

            return PostgresStore(dsn=cfg.read_dsn or cfg.dsn, pool_size=cfg.pool_size)
        if cfg.read_backend != "memory":
            logger.warning("unrecognized read store backend {!r}, falling back to MemoryStore", cfg.read_backend)
        return MemoryStore()

    def __build_authz(self) -> AccessControl | None:
        return build_authz(self.__config.authz)

    def __start_metrics_export(self) -> None:
        if not self.__metrics or self.__config.metrics.export_interval <= 0:
            return
        if self.__config.tracing.exporter != "otlp":
            return

        def on_snapshot(snap: dict) -> None:
            if not any([snap.get("counters"), snap.get("timers"), snap.get("gauges")]):
                return
            logger.debug(
                "exporting {} counters, {} timers, {} gauges",
                len(snap.get("counters", {})),
                len(snap.get("timers", {})),
                len(snap.get("gauges", {})),
            )

        self.__metrics_exporter = MetricsExporter(
            metrics=self.__metrics,
            interval_seconds=float(self.__config.metrics.export_interval),
            on_snapshot=on_snapshot,
        )
        self.__metrics_exporter.start()

    def __register_subsystem_health(self) -> None:
        bus = self.__bus

        def __bus_health() -> dict:
            subs = 0
            getter = getattr(bus, "subscriber_count", None)
            if callable(getter):
                try:
                    subs = int(getter())
                except (TypeError, ValueError, AttributeError):
                    logger.exception("bus subscriber_count failed")
            dlq = 0
            dlq_obj = getattr(bus, "dlq", None)
            if dlq_obj is not None:
                dlq = int(getattr(dlq_obj, "count", 0))
            stopped = bool(getattr(bus, "is_stopped", lambda: False)())
            return {
                "ok": not stopped,
                "subscribers": subs,
                "dlq_count": dlq,
            }

        self.__health.register("bus", __bus_health)
        self.__health.register("store", lambda: self.__store.health())
        read_store = self.__read_store
        if read_store is not None:
            self.__health.register("read_store", lambda: read_store.health())
        self.__health.register(
            "services",
            lambda: {
                "ok": True,
                "running": [sid for sid, svc in self.__services.items() if svc.is_running],
            },
        )
        if self.__metrics:

            def _metrics_health() -> dict:
                return {"ok": True}

            self.__health.register("metrics", _metrics_health)
        tracer = self.__tracer
        if tracer is not None:
            self.__health.register("tracer", lambda: {"ok": True, "spans": len(tracer.spans)})
        if self.__saga:
            self.__health.register("saga", lambda: {"ok": True})
        if hasattr(self.__bus, "dlq") and self.__bus.dlq:
            self.__health.register(
                "dlq",
                lambda: {
                    "ok": True,
                    "dead_letter_count": self.__bus.dlq.count,
                },
            )
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
        with self.__lock:
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

    def register(self, service_name: str, identity: Identity | None = None) -> NanoService:
        """Instantiates a nano service by name and registers it."""
        module_path = HANDLER_MAP.get(service_name)
        if not module_path:
            raise ServiceNotFoundError(f"unknown service: {service_name}")
        class_name = HANDLER_CLASSES.get(service_name)
        if not class_name:
            raise ServiceNotFoundError(f"no class mapping for service: {service_name}")
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name, None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, NanoService)):
            raise ServiceNotFoundError(f"class {class_name} not found in {module_path}")
        extra: dict[str, Any] = {}
        if service_name == "fee":
            extra["fee_schedules"] = dict(self.__config.fee.schedules)
            extra["penal_interest_daily_rate"] = self.__config.fee.penal_interest_daily_rate
            extra["late_payment_percent"] = self.__config.fee.late_payment_percent
            extra["max_penal_interest_per_loan"] = self.__config.fee.max_penal_interest_per_loan
        elif service_name == "kfs":
            extra["cooling_off_days"] = 3
        elif service_name == "governance":
            extra["param_ranges"] = {k: list(v) for k, v in self.__config.governance.param_ranges.items()}
            extra["param_defaults"] = dict(self.__config.governance.param_defaults)
        elif service_name == "npa":
            nconf = self.__config.npa
            extra["standard_provisioning_rate"] = nconf.standard_provisioning_rate
            extra["substandard_provisioning_rate"] = nconf.substandard_provisioning_rate
            extra["doubtful_provisioning_rate_secured"] = nconf.doubtful_provisioning_rate_secured
            extra["loss_provisioning_rate"] = nconf.loss_provisioning_rate
            extra["npa_days"] = nconf.npa_days
            extra["dlg_trigger_days"] = nconf.dlg_trigger_days
        elif service_name == "audit":
            extra["max_ledger"] = self.__config.audit.max_ledger
            extra["export_url"] = self.__config.audit.export_url
        elif service_name == "razorpay":
            rconf = self.__config.razorpay
            extra["key_id"] = rconf.key_id
            extra["key_secret"] = rconf.key_secret
            extra["webhook_secret"] = rconf.webhook_secret
            extra["api_base_url"] = rconf.api_base_url
        elif service_name == "compliance":
            extra["kyc_providers"] = self.__kyc_providers
        elif service_name == "credit_bureau":
            extra["kyc_providers"] = self.__kyc_providers
        elif service_name == "consent":
            cconf = self.__config.dpdpa.consent
            extra["required_purposes"] = list(cconf.required_purposes)
            extra["consent_validity_days"] = cconf.consent_validity_days
        elif service_name == "dsr":
            dconf = self.__config.dpdpa.dsr
            extra["response_time_days"] = dconf.response_time_days
            extra["grievance_response_days"] = dconf.grievance_response_days
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
            secrets_manager=self.__secrets,
            **extra,
        )
        with self.__lock:
            self.__services[service_name] = svc
        if self.__health:
            svc_id = service_name
            self.__health.register(f"service:{svc_id}", svc.health_check)
        return svc

    def wire(self, service_name: str) -> None:
        """Subscribes a service to all event types it cares about."""
        svc = self.__services.get(service_name)
        if not svc:
            logger.warning("wire called for unregistered service {}", service_name)
            return
        for event_type, subscribers in WIRING.items():
            if service_name in subscribers:
                svc.subscribe(event_type)
        svc.subscribe(service_name)

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    def start(self, service_names: list[str] | None = None) -> None:
        """Starts the event bus and selected services.

        Args:
            service_names: List of services to start.  If ``None``,
                starts only the services enabled in configuration.
        """
        if service_names is None:
            service_names = self.__config.enabled_services()
        self.__service_names = list(service_names)
        self.__run_migrations()
        self.__start_metrics_export()
        with self.__lock:
            registered: list[str] = [n for n in service_names if n not in self.__services]
        for name in registered:
            self.register(name)
        for name in service_names:
            self.wire(name)
        with self.__lock:
            for name in service_names:
                svc = self.__services.get(name)
                if svc:
                    svc.start()
        self.__bus.start()

    def restart_failing_services(self) -> list[str]:
        """Restarts services that have recorded failures under the supervisor.

        Each failing service is stopped, re-registered, re-wired, and started.
        Services that have exceeded max restarts are not restarted.

        Returns:
            List of service IDs that were restarted.
        """
        if self.__supervisor is None:
            return []
        restarted: list[str] = []
        for service_id in self.__supervisor.failing_services():
            if not self.__supervisor.should_restart(service_id):
                continue
            with self.__lock:
                if service_id not in self.__services:
                    self.__supervisor.reset(service_id)
                    continue
                logger.warning("restarting failing service {}", service_id)
                try:
                    old = self.__services.pop(service_id)
                    old.stop()
                except (OSError, RuntimeError, ValueError):
                    logger.exception("error stopping service {} during restart", service_id)
                    continue
            try:
                svc = self.register(service_id)
                self.wire(service_id)
                svc.start()
                self.__supervisor.record_restart(service_id)
                self.__supervisor.reset(service_id)
                restarted.append(service_id)
                logger.info("service {} restarted successfully", service_id)
            except (OSError, RuntimeError, ValueError, KeyError):
                logger.exception("failed to restart service {}", service_id)
        return restarted

    def stop(self) -> None:
        """Stops all services, the metrics export loop, and the event bus."""
        errors: list[str] = []
        try:
            if self.__metrics_exporter is not None:
                self.__metrics_exporter.stop()
        except Exception as exc:
            errors.append(f"metrics_exporter: {exc}")
        for svc in self.__services.values():
            try:
                svc.stop()
            except Exception as exc:
                errors.append(f"service {svc.service_id}: {exc}")
        try:
            self.__bus.stop()
        except Exception as exc:
            errors.append(f"bus: {exc}")
        try:
            self.__store.shutdown()
        except Exception as exc:
            errors.append(f"store: {exc}")
        if self.__read_store is not None:
            try:
                self.__read_store.shutdown()
            except Exception as exc:
                errors.append(f"read_store: {exc}")
        if self.__supervisor is not None:
            try:
                self.__supervisor.shutdown()
            except Exception as exc:
                errors.append(f"supervisor: {exc}")
        try:
            self.__health.shutdown()
        except Exception as exc:
            errors.append(f"health: {exc}")
        if errors:
            logger.error("Runtime.stop completed with {} error(s): {}", len(errors), "; ".join(errors))

    def get(self, service_name: str) -> NanoService | None:
        """Returns a registered service by name, or ``None``."""
        return self.__services.get(service_name)

    def publish(self, event_type: str, payload: dict[str, Any], correlation_id: str = "") -> str:
        """Publishes an event directly to the bus (used for external input).

        The event is signed with the runtime identity so subscribers with
        authz enabled can verify its provenance against the runtime's
        public key.
        """
        event = self.__sign_outbound_event(event_type, payload, correlation_id)
        return self.__bus.publish(event)

    def publish_as(
        self,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str = "",
    ) -> str:
        """Publishes an event on behalf of *source*.

        The runtime looks up or lazily creates an Ed25519 identity for
        the requested service id (persisted through the runtime
        ``SecretsManager`` when one is configured) and signs the event
        with that identity so downstream subscribers can attribute the
        event to the requested source rather than to the runtime.

        Args:
            source: Service id the caller is publishing as. Must match
                ``[a-z][a-z0-9_.-]+``.
            event_type: Event type being published.
            payload: Event payload.
            correlation_id: Optional correlation id.

        Returns:
            The dispatched event's id.

        Raises:
            PermissionError: If authz is enabled and ``source`` is not
                trusted, or if the source id is invalid.
        """
        if not source or not _VALID_SOURCE_RE.match(source):
            raise PermissionError(f"invalid source id: {source!r}")
        if self.__authz is not None and not self.__authz.is_trusted(source):
            raise PermissionError(f"source {source!r} is not trusted")
        identity = self.__identity_for(source)
        event = Event(
            event_type=event_type,
            source=identity.service_id,
            source_key=identity.public_key,
            payload=payload,
            correlation_id=correlation_id or "",
        )
        signed = identity.sign(event.canonical_sign_bytes().decode("utf-8"))
        event = dataclasses.replace(event, signature=signed)
        if self.__authz is not None:
            self.__authz.trust(identity.service_id, identity.public_key)
        return self.__bus.publish(event)

    def __identity_for(self, service_id: str) -> Identity:
        existing = self.__publisher_identities.get(service_id)
        if existing is not None:
            return existing
        identity = Identity.create(service_id, secrets_manager=self.__secrets)
        with self.__publisher_lock:
            self.__publisher_identities[service_id] = identity
        return identity

    def __sign_outbound_event(self, event_type: str, payload: dict[str, Any], correlation_id: str) -> Event:
        identity: Identity | None = self.__runtime_identity
        if identity is None:
            return Event(
                event_type=event_type,
                source="runtime",
                source_key="",
                payload=payload,
                correlation_id=correlation_id or "",
            )
        event = Event(
            event_type=event_type,
            source=identity.service_id,
            source_key=identity.public_key,
            payload=payload,
            correlation_id=correlation_id or "",
        )
        signed = identity.sign(event.canonical_sign_bytes().decode("utf-8"))
        event = dataclasses.replace(event, signature=signed)
        if self.__authz is not None:
            self.__authz.trust(identity.service_id, identity.public_key)
        return event

    async def async_publish(self, event_type: str, payload: dict[str, Any], correlation_id: str = "") -> str:
        """Async variant of ``publish`` for use in async contexts (e.g. FastAPI).

        Dispatches the synchronous publish to a thread pool to avoid
        blocking the async event loop.
        """
        import asyncio

        return await asyncio.to_thread(self.publish, event_type, payload, correlation_id)

    def replay_saga(self, saga_id: str) -> bool:
        """Replays an incomplete saga for crash recovery.

        Delegates to ``SagaOrchestrator.replay_saga``.
        """
        if self.__saga is None:
            logger.warning("replay_saga: sagas are disabled")
            return False
        return self.__saga.replay_saga(saga_id)
