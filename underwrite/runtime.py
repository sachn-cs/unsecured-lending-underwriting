# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

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
    "build_authz",
    "build_event_bus",
    "build_kyc_providers",
    "build_read_store",
    "build_secrets",
    "build_store",
    "build_supervisor",
    "build_tracer",
    "register_subsystem_health",
    "run_migrations",
    "start_metrics_export",
]

import dataclasses
import importlib
import re
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.config import Configuration
from underwrite.exceptions import ServiceNotFoundError
from underwrite.exporter import Exporter
from underwrite.handler import HANDLER_CLASSES, HANDLER_MAP, WIRING
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.logger import JsonFormatter, TextFormatter, logger, loguru_sink_format
from underwrite.message import Message
from underwrite.metrics import Collector
from underwrite.migrate import default_plan
from underwrite.saga import Orchestrator
from underwrite.secrets import Manager
from underwrite.services.kyc.base import Provider
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer

if TYPE_CHECKING:
    from underwrite.services.base import Core


def build_secrets(config: Configuration) -> Manager | None:
    cfg = config.secrets
    if cfg.backend == "none":
        return None
    return Manager(config=cfg)


def build_supervisor(config: Configuration) -> Watcher | None:
    cfg = config.recovery
    if not cfg.auto_restart:
        return None
    return Watcher(
        max_restarts=cfg.max_restarts,
        backoff_seconds=cfg.backoff_seconds,
    )


def build_kyc_providers(config: Configuration, secrets: Manager | None) -> dict[str, Provider]:
    """Resolve the configured KYC provider clients.

    Returns a dict mapping the provider name (``pan`` /
    ``aadhaar`` / ``cibil`` / ``ckyc``) to the configured
    client instance. When ``kyc_providers`` is not in the
    configuration, returns an empty dict; the compliance and
    credit_bureau services then fall back to format-only
    validation.
    """
    kp = getattr(config, "kyc_providers", None)
    if kp is None:
        return {}
    return kp.all(secrets) if kp is not None else {}


def build_tracer(config: Configuration) -> Tracer | None:
    if not config.tracing.enabled:
        return None
    from underwrite.tracer import Console, Otlp, SpanExporter

    exporter: SpanExporter | None = None
    if config.tracing.exporter == "console":
        exporter = Console()
    elif config.tracing.exporter == "otlp":
        exporter = Otlp(service_name="underwrite")
    return Tracer(name="runtime", exporter=exporter)


def build_store(config: Configuration) -> Store:
    cfg = config.store
    if cfg.backend == "filesystem":
        return Store(type=Store.DISK, data_dir=config.data_dir)
    elif cfg.backend == "memory":
        return Store(type=Store.MEMORY)
    logger.warning("unrecognized store backend {!r}, falling back to Disk", cfg.backend)
    return Store(type=Store.DISK, data_dir=config.data_dir)


def build_read_store(config: Configuration) -> Store | None:
    cfg = config.store
    if not cfg.read_backend:
        return None
    if cfg.read_backend == "filesystem":
        return Store(type=Store.DISK, data_dir=config.data_dir)
    logger.warning("unrecognized read store backend {!r}, falling back to InMemory", cfg.read_backend)
    return Store(type=Store.MEMORY)


def start_metrics_export(metrics_collector: Collector | None, config: Configuration) -> Exporter | None:
    if not metrics_collector or config.metrics.export_interval <= 0:
        return None
    if config.tracing.exporter != "otlp":
        return None

    def on_snapshot(snap: dict) -> None:
        if not any([snap.get("counters"), snap.get("timers"), snap.get("gauges")]):
            return
        logger.debug(
            "exporting {} counters, {} timers, {} gauges",
            len(snap.get("counters", {})),
            len(snap.get("timers", {})),
            len(snap.get("gauges", {})),
        )

    exporter = Exporter(
        metrics=metrics_collector,
        interval_seconds=float(config.metrics.export_interval),
        on_snapshot=on_snapshot,
    )
    exporter.start()
    return exporter


def register_subsystem_health(runtime: Runtime) -> None:
    bus = runtime.bus

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

    runtime.health.register("bus", __bus_health)
    runtime.health.register("store", lambda: runtime.store.health())
    read_store = runtime.read_store
    if read_store is not None:
        runtime.health.register("read_store", lambda: read_store.health())
    runtime.health.register(
        "services",
        lambda: {
            "ok": True,
            "running": [sid for sid, svc in runtime.services.items() if svc.is_running],
        },
    )
    if runtime.metrics:

        def _metrics_health() -> dict:
            return {"ok": True}

        runtime.health.register("metrics", _metrics_health)
    tracer = runtime.tracer
    if tracer is not None:
        runtime.health.register("tracer", lambda: {"ok": True, "spans": len(tracer.spans)})
    if runtime.saga:
        runtime.health.register("saga", lambda: {"ok": True})
    if hasattr(bus, "dlq") and bus.dlq:
        runtime.health.register(
            "dlq",
            lambda: {
                "ok": True,
                "dead_letter_count": bus.dlq.count,
            },
        )
    if runtime.supervisor:
        sup = runtime.supervisor
        runtime.health.register("supervisor", lambda: sup.health())


def run_migrations(store: Store, config: Configuration) -> None:
    if config.migration.auto_migrate:
        plan = default_plan()
        store.migrate(plan)


def build_event_bus(bus_config: Any, store: Store) -> EventBus:
    """Construct the configured EventBus backend."""
    backend = bus_config.backend
    if backend == "modal":
        from underwrite.modal import ModalBus

        return ModalBus(
            queue_name=bus_config.modal_queue_name,
            store=store,
        )
    bus = LocalBus(
        rate_limit=bus_config.rate_limit,
        max_workers=bus_config.max_workers,
        max_futures=bus_config.max_futures,
        store=store,
    )
    return bus  # type: ignore[return-value]


def build_authz(authz_config: Any) -> AccessControl | None:
    """Build an AccessControl from AuthzConfig."""
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


class Runtime:
    """Manages lifecycle of all nano services with health, metrics, authz, migration, tracing, and saga."""

    __store: Store
    __read_store: Store | None
    __services: dict[str, Core]
    __bus: EventBus
    __health: Checks
    __tracer: Tracer | None
    __secrets: Manager | None
    __saga: Orchestrator | None
    __metrics: Collector | None
    __authz: AccessControl | None
    __supervisor: Watcher | None
    __metrics_exporter: Exporter | None
    __runtime_identity: Keypair | None
    __publisher_identities: dict[str, Keypair]
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
        self.config: Configuration = config or Configuration.load()
        self.configure_logging()
        self.store = build_store(self.config)
        self.read_store = build_read_store(self.config)
        self.services: dict[str, Core] = {}
        self.lock: threading.RLock = threading.RLock()
        self.runtime_identity = None
        self.publisher_identities: dict[str, Keypair] = {}
        self.publisher_lock = threading.Lock()
        if readonly:
            self.bus = cast(EventBus | LocalBus, LocalBus(store=self.store))
            self.health = Checks()
            self.tracer = None
            self.secrets = None
            self.saga = None
            self.metrics = None
            self.authz = None
            self.supervisor = None
            self.metrics_exporter = None
            register_subsystem_health(self)
            return
        self.runtime_identity = None
        self.secrets = build_secrets(self.config)
        self.runtime_identity = Keypair.create("runtime", secrets_manager=self.secrets)
        self.kyc_providers = build_kyc_providers(self.config, self.secrets)
        self.tracer = build_tracer(self.config)
        self.bus = cast(EventBus | LocalBus, build_event_bus(self.config.bus, self.store))
        self.saga = Orchestrator(store=self.store) if self.config.saga.enabled else None
        self.health = Checks()
        self.metrics = Collector() if self.config.metrics.enabled else None
        self.authz = build_authz(self.config.authz)
        if self.authz is not None and self.runtime_identity is not None:
            self.authz.trust(self.runtime_identity.name, self.runtime_identity.public_key)
        self.supervisor = build_supervisor(self.config)
        self.metrics_exporter = None

        register_subsystem_health(self)

    def configure_logging(self) -> None:
        cfg = self.config.logging
        sink = sys.stdout if cfg.output == "stdout" else sys.stderr
        formatter = JsonFormatter() if cfg.log_format == "json" else TextFormatter()
        logger.remove()
        logger.add(sink, level=cfg.level, format=loguru_sink_format(formatter), colorize=False)











    def register(self, service_name: str, identity: Keypair | None = None) -> Core:
        """Instantiates a nano service by name and registers it."""
        module_path = HANDLER_MAP.get(service_name)
        if not module_path:
            raise ServiceNotFoundError(f"unknown service: {service_name}")
        class_name = HANDLER_CLASSES.get(service_name)
        if not class_name:
            raise ServiceNotFoundError(f"no class mapping for service: {service_name}")
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name, None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, object)):
            raise ServiceNotFoundError(f"class {class_name} not found in {module_path}")
        extra: dict[str, Any] = {}
        if service_name == "fee":
            extra["fee_schedules"] = dict(self.config.fee.schedules)
            extra["penal_interest_daily_rate"] = self.config.fee.penal_interest_daily_rate
            extra["late_payment_percent"] = self.config.fee.late_payment_percent
            extra["max_penal_interest_per_loan"] = self.config.fee.max_penal_interest_per_loan
        elif service_name == "kfs":
            extra["cooling_off_days"] = 3
        elif service_name == "governance":
            extra["param_ranges"] = {k: list(v) for k, v in self.config.governance.param_ranges.items()}
            extra["param_defaults"] = dict(self.config.governance.param_defaults)
        elif service_name == "npa":
            nconf = self.config.npa
            extra["standard_provisioning_rate"] = nconf.standard_provisioning_rate
            extra["substandard_provisioning_rate"] = nconf.substandard_provisioning_rate
            extra["doubtful_provisioning_rate_secured"] = nconf.doubtful_provisioning_rate_secured
            extra["loss_provisioning_rate"] = nconf.loss_provisioning_rate
            extra["npa_days"] = nconf.npa_days
            extra["dlg_trigger_days"] = nconf.dlg_trigger_days
        elif service_name == "audit":
            extra["max_ledger"] = self.config.audit.max_ledger
            extra["export_url"] = self.config.audit.export_url
        elif service_name == "razorpay":
            rconf = self.config.razorpay
            extra["key_id"] = rconf.key_id
            extra["key_secret"] = rconf.key_secret
            extra["webhook_secret"] = rconf.webhook_secret
            extra["api_base_url"] = rconf.api_base_url
        elif service_name == "compliance":
            extra["kyc_providers"] = self.kyc_providers
        elif service_name == "credit_bureau":
            extra["kyc_providers"] = self.kyc_providers
        elif service_name == "consent":
            cconf = self.config.dpdpa.consent
            extra["required_purposes"] = list(cconf.required_purposes)
            extra["consent_validity_days"] = cconf.consent_validity_days
        elif service_name == "dsr":
            dconf = self.config.dpdpa.dsr
            extra["response_time_days"] = dconf.response_time_days
            extra["grievance_response_days"] = dconf.grievance_response_days
        svc = cls(
            name=service_name,
            identity=identity,
            bus=self.bus,
            store=self.store,
            metrics=self.metrics,
            health=self.health,
            authz=self.authz,
            tracer=self.tracer,
            saga=self.saga,
            supervisor=self.supervisor,
            secrets_manager=self.secrets,
            **extra,
        )
        with self.lock:
            self.services[service_name] = svc
        if self.health:
            svc_id = service_name
            self.health.register(f"service:{svc_id}", svc.health_check)
        return svc

    def wire(self, service_name: str) -> None:
        """Subscribes a service to all event types it cares about."""
        svc = self.services.get(service_name)
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
            service_names = self.config.enabled_services()
        self.service_names = list(service_names)
        run_migrations(self.store, self.config)
        self.metrics_exporter = start_metrics_export(self.metrics, self.config)  # type: ignore[assignment]
        with self.lock:
            registered: list[str] = [n for n in service_names if n not in self.services]
        for name in registered:
            self.register(name)
        for name in service_names:
            self.wire(name)
        with self.lock:
            for name in service_names:
                svc = self.services.get(name)
                if svc:
                    svc.start()
        self.bus.start()

    def restart_failing_services(self) -> list[str]:
        """Restarts services that have recorded failures under the supervisor.

        Each failing service is stopped, re-registered, re-wired, and started.
        Services that have exceeded max restarts are not restarted.

        Returns:
            List of service IDs that were restarted.
        """
        if self.supervisor is None:
            return []
        restarted: list[str] = []
        for service_id in self.supervisor.failing_services():
            if not self.supervisor.should_restart(service_id):
                continue
            with self.lock:
                if service_id not in self.services:
                    self.supervisor.reset(service_id)
                    continue
                logger.warning("restarting failing service {}", service_id)
                try:
                    old = self.services.pop(service_id)
                    old.stop()
                except (OSError, RuntimeError, ValueError):
                    logger.exception("error stopping service {} during restart", service_id)
                    continue
            try:
                svc = self.register(service_id)
                self.wire(service_id)
                svc.start()
                self.supervisor.record_restart(service_id)
                self.supervisor.reset(service_id)
                restarted.append(service_id)
                logger.info("service {} restarted successfully", service_id)
            except (OSError, RuntimeError, ValueError, KeyError):
                logger.exception("failed to restart service {}", service_id)
        return restarted

    def stop(self) -> None:
        """Stops all services, the metrics export loop, and the event bus."""
        errors: list[str] = []
        try:
            if self.metrics_exporter is not None:
                self.metrics_exporter.stop()
        except Exception as exc:
            errors.append(f"metrics_exporter: {exc}")
        for svc in self.services.values():
            try:
                svc.stop()
            except Exception as exc:
                errors.append(f"service {svc.service_id}: {exc}")
        try:
            self.bus.stop()
        except Exception as exc:
            errors.append(f"bus: {exc}")
        try:
            self.store.shutdown()
        except Exception as exc:
            errors.append(f"store: {exc}")
        if self.read_store is not None:
            try:
                self.read_store.shutdown()
            except Exception as exc:
                errors.append(f"read_store: {exc}")
        if self.supervisor is not None:
            try:
                self.supervisor.shutdown()
            except Exception as exc:
                errors.append(f"supervisor: {exc}")
        try:
            self.health.shutdown()
        except Exception as exc:
            errors.append(f"health: {exc}")
        if errors:
            logger.error("Runtime.stop completed with {} error(s): {}", len(errors), "; ".join(errors))

    def get(self, service_name: str) -> Core | None:
        """Returns a registered service by name, or ``None``."""
        return self.services.get(service_name)

    def publish(self, event_type: str, payload: dict[str, Any], correlation_id: str = "") -> str:
        """Publishes an event directly to the bus (used for external input).

        The event is signed with the runtime identity so subscribers with
        authz enabled can verify its provenance against the runtime's
        public key.
        """
        event = self.sign_outbound_event(event_type, payload, correlation_id)
        return self.bus.publish(event)

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
        ``Manager`` when one is configured) and signs the event
        with that identity so downstream subscribers can attribute the
        event to the requested source rather than to the runtime.

        Args:
            source: Service id the caller is publishing as. Must match
                ``[a-z][a-z0-9_.-]+``.
            event_type: Message type being published.
            payload: Message payload.
            correlation_id: Optional correlation id.

        Returns:
            The dispatched event's id.

        Raises:
            PermissionError: If authz is enabled and ``source`` is not
                trusted, or if the source id is invalid.
        """
        if not source or not _VALID_SOURCE_RE.match(source):
            raise PermissionError(f"invalid source id: {source!r}")
        if self.authz is not None and not self.authz.is_trusted(source):
            raise PermissionError(f"source {source!r} is not trusted")
        identity = self.identity_for(source)
        event = Message(
            event_type=event_type,
            source=identity.name,
            source_key=identity.public_key,
            payload=payload,
            correlation_id=correlation_id or "",
        )
        signed = identity.sign(event.canonical_sign_bytes().decode("utf-8"))
        event = dataclasses.replace(event, signature=signed)
        if self.authz is not None:
            self.authz.trust(identity.name, identity.public_key)
        return self.bus.publish(event)

    def identity_for(self, service_id: str) -> Keypair:
        existing = self.publisher_identities.get(service_id)
        if existing is not None:
            return existing
        identity = Keypair.create(service_id, secrets_manager=self.secrets)
        with self.publisher_lock:
            self.publisher_identities[service_id] = identity
        return identity

    def sign_outbound_event(self, event_type: str, payload: dict[str, Any], correlation_id: str) -> Message:
        identity: Keypair | None = self.runtime_identity
        if identity is None:
            return Message(
                event_type=event_type,
                source="runtime",
                source_key="",
                payload=payload,
                correlation_id=correlation_id or "",
            )
        event = Message(
            event_type=event_type,
            source=identity.name,
            source_key=identity.public_key,
            payload=payload,
            correlation_id=correlation_id or "",
        )
        signed = identity.sign(event.canonical_sign_bytes().decode("utf-8"))
        event = dataclasses.replace(event, signature=signed)
        if self.authz is not None:
            self.authz.trust(identity.name, identity.public_key)
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

        Delegates to ``Orchestrator.replay_saga``.
        """
        if self.saga is None:
            logger.warning("replay_saga: sagas are disabled")
            return False
        return self.saga.replay_saga(saga_id)


_VALID_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_.-]+$")
