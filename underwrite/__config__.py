"""Core configuration engine for the underwrite nano-service platform.

All services are configuration-driven. A JSON config determines:
  - Which services are enabled
  - How each service connects (bus, store, identity)
  - Service-specific parameters

Usage:
    from underwrite.config import Configuration

    config = Configuration.load("config.yaml")
    config.services["risk"].enabled  # True/False
"""

from __future__ import annotations

__all__ = [
    "AuthzConfig",
    "BusConfig",
    "Configuration",
    "IdentityConfig",
    "LoggingConfig",
    "MetricsConfig",
    "MigrationConfig",
    "RecoveryConfig",
    "SagaConfig",
    "SecretsConfig",
    "SERVICE_NAMES",
    "ServiceConfig",
    "StoreConfig",
    "TracingConfig",
]

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from underwrite.__exceptions__ import ConfigurationError


@dataclass
class ServiceConfig:
    """Configuration for a single nano service."""

    enabled: bool = False
    priority: int = 0


@dataclass
class BusConfig:
    """Event bus configuration."""

    backend: str = "local"  # local | sqs | modal
    rate_limit: float = 0.0  # 0 = unlimited
    max_workers: int = 0  # 0 = synchronous, >0 = thread pool size


@dataclass
class StoreConfig:
    """State store configuration."""

    backend: str = "memory"  # memory | filesystem | postgres
    dsn: str = ""  # connection string for postgres
    pool_size: int = 5
    read_backend: str = ""  # separate read store for CQRS
    read_dsn: str = ""


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    output: str = "stdout"  # stdout | file | s3
    log_format: str = "text"  # text | json


@dataclass
class IdentityConfig:
    """Service identity configuration."""

    private_key: str = ""
    public_key: str = ""
    key_ttl: float = 86400.0
    key_grace: float = 3600.0


@dataclass
class AuthzConfig:
    """Access-control configuration."""

    enabled: bool = False
    policy_file: str = ""  # path to JSON policy file


@dataclass
class MetricsConfig:
    """Metrics configuration."""

    enabled: bool = True
    export_interval: int = 60  # seconds between snapshot exports


@dataclass
class MigrationConfig:
    """Schema migration configuration."""

    auto_migrate: bool = True  # apply pending migrations on startup


@dataclass
class TracingConfig:
    """Distributed tracing configuration."""

    enabled: bool = False
    exporter: str = "console"  # console | otlp | noop


@dataclass
class SagaConfig:
    """Saga orchestration configuration."""

    enabled: bool = True


@dataclass
class SecretsConfig:
    """Secrets backend configuration for private-key management."""
    backend: str = "env"  # env | vault | aws
    url: str = ""  # Vault URL
    token: str = ""  # Vault token (prefer VAULT_TOKEN env var)
    region: str = ""  # AWS region for Secrets Manager


@dataclass
class RecoveryConfig:
    """Auto-recovery configuration for crashed services."""
    auto_restart: bool = True
    max_restarts: int = 3
    backoff_seconds: float = 1.0


@dataclass
class Configuration:
    """Root configuration object."""

    bus: BusConfig = field(default_factory=BusConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    authz: AuthzConfig = field(default_factory=AuthzConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    migration: MigrationConfig = field(default_factory=MigrationConfig)
    tracing: TracingConfig = field(default_factory=TracingConfig)
    saga: SagaConfig = field(default_factory=SagaConfig)
    services: dict[str, ServiceConfig] = field(default_factory=dict)
    data_dir: str = "./data"
    secrets: SecretsConfig = field(default_factory=SecretsConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)

    @classmethod
    def default(cls) -> Configuration:
        """Returns a default configuration with all services listed but disabled."""
        config = Configuration()
        config.store.backend = "filesystem"
        for service_name in SERVICE_NAMES:
            config.services[service_name] = ServiceConfig(enabled=False)
        return config

    @classmethod
    def load(cls, path: str | None = None) -> Configuration:
        """Loads configuration from a JSON file, env vars, or returns defaults."""
        config = cls.default()
        env = os.environ.get("UNDERWRITE_ENV", "")
        # Try env-specific config files first
        for candidate in ([path] if path else []):
            if candidate and Path(candidate).exists():
                with open(candidate) as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ConfigurationError("config root must be a JSON object")
                config = cls.__merge(config, data)
                break
        else:
            # Try UNDERWRITE_ENV-specific file
            if env:
                env_path = f"config.{env}.json"
                if Path(env_path).exists():
                    with open(env_path) as fh:
                        data = json.load(fh)
                    if not isinstance(data, dict):
                        raise ConfigurationError("config root must be a JSON object")
                    config = cls.__merge(config, data)
        config = cls.__apply_env_overrides(config)
        return config

    def save(self, path: str) -> None:
        """Persists configuration to a JSON file."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    def to_dict(self) -> dict[str, Any]:
        """Serialises configuration to a dictionary."""
        return {
            "bus": {
                "backend": self.bus.backend,
                "rate_limit": self.bus.rate_limit,
                "max_workers": self.bus.max_workers
            },
            "store": {
                "backend": self.store.backend,
                "dsn": self.store.dsn,
                "pool_size": self.store.pool_size,
                "read_backend": self.store.read_backend,
                "read_dsn": self.store.read_dsn
            },
            "logging": {
                "level": self.logging.level,
                "output": self.logging.output,
                "format": self.logging.log_format,
            },
            "identity": {
                "public_key": self.identity.public_key,
                "key_ttl": self.identity.key_ttl,
                "key_grace": self.identity.key_grace
            },
            "authz": {
                "enabled": self.authz.enabled,
                "policy_file": self.authz.policy_file
            },
            "metrics": {
                "enabled": self.metrics.enabled,
                "export_interval": self.metrics.export_interval
            },
            "migration": {
                "auto_migrate": self.migration.auto_migrate
            },
            "tracing": {
                "enabled": self.tracing.enabled,
                "exporter": self.tracing.exporter
            },
            "saga": {
                "enabled": self.saga.enabled
            },
            "secrets": {
                "backend": self.secrets.backend,
                "url": self.secrets.url,
                "token": self.secrets.token,
                "region": self.secrets.region,
            },
            "recovery": {
                "auto_restart": self.recovery.auto_restart,
                "max_restarts": self.recovery.max_restarts,
                "backoff_seconds": self.recovery.backoff_seconds,
            },
            "services": {
                name: {
                    "enabled": svc.enabled,
                    "priority": svc.priority
                } for name, svc in self.services.items()
            },
            "data_dir": self.data_dir,
        }

    def enabled_services(self) -> list[str]:
        """Returns the list of enabled service names."""
        return [name for name, svc in self.services.items() if svc.enabled]

    @classmethod
    def __merge(cls, config: Configuration, data: dict[str,
                                                       Any]) -> Configuration:
        known_keys = {
            "bus", "store", "logging", "identity", "data_dir", "services",
            "authz", "metrics", "migration", "tracing", "saga", "secrets",
            "recovery"
        }
        unknown = set(data.keys()) - known_keys
        if unknown:
            raise ConfigurationError(
                f"unknown config keys: {', '.join(sorted(unknown))}")
        if "bus" in data:
            config.bus.backend = data["bus"].get("backend", config.bus.backend)
            config.bus.rate_limit = data["bus"].get("rate_limit",
                                                    config.bus.rate_limit)
            config.bus.max_workers = data["bus"].get("max_workers",
                                                     config.bus.max_workers)
        if "store" in data:
            config.store.backend = data["store"].get("backend",
                                                     config.store.backend)
            config.store.dsn = data["store"].get("dsn", config.store.dsn)
            config.store.pool_size = data["store"].get("pool_size",
                                                       config.store.pool_size)
            config.store.read_backend = data["store"].get(
                "read_backend", config.store.read_backend)
            config.store.read_dsn = data["store"].get("read_dsn",
                                                      config.store.read_dsn)
        if "logging" in data:
            config.logging.level = data["logging"].get("level",
                                                       config.logging.level)
            config.logging.output = data["logging"].get("output",
                                                         config.logging.output)
            config.logging.log_format = data["logging"].get(
                "format", config.logging.log_format)
        if "identity" in data:
            config.identity.private_key = data["identity"].get(
                "private_key", config.identity.private_key)
            config.identity.public_key = data["identity"].get(
                "public_key", config.identity.public_key)
            config.identity.key_ttl = data["identity"].get(
                "key_ttl", config.identity.key_ttl)
            config.identity.key_grace = data["identity"].get(
                "key_grace", config.identity.key_grace)
        if "authz" in data:
            config.authz.enabled = data["authz"].get("enabled",
                                                     config.authz.enabled)
            config.authz.policy_file = data["authz"].get(
                "policy_file", config.authz.policy_file)
        if "metrics" in data:
            config.metrics.enabled = data["metrics"].get(
                "enabled", config.metrics.enabled)
            config.metrics.export_interval = data["metrics"].get(
                "export_interval", config.metrics.export_interval)
        if "migration" in data:
            config.migration.auto_migrate = data["migration"].get(
                "auto_migrate", config.migration.auto_migrate)
        if "tracing" in data:
            config.tracing.enabled = data["tracing"].get(
                "enabled", config.tracing.enabled)
            config.tracing.exporter = data["tracing"].get(
                "exporter", config.tracing.exporter)
        if "saga" in data:
            config.saga.enabled = data["saga"].get("enabled",
                                                    config.saga.enabled)
        if "secrets" in data:
            config.secrets.backend = data["secrets"].get("backend", config.secrets.backend)
            config.secrets.url = data["secrets"].get("url", config.secrets.url)
            config.secrets.token = data["secrets"].get("token", config.secrets.token)
            config.secrets.region = data["secrets"].get("region", config.secrets.region)
        if "recovery" in data:
            config.recovery.auto_restart = data["recovery"].get("auto_restart", config.recovery.auto_restart)
            config.recovery.max_restarts = data["recovery"].get("max_restarts", config.recovery.max_restarts)
            config.recovery.backoff_seconds = data["recovery"].get("backoff_seconds", config.recovery.backoff_seconds)
        if "data_dir" in data:
            config.data_dir = data["data_dir"]
        if "services" in data:
            for name, svc_data in data["services"].items():
                config.services[name] = ServiceConfig(
                    enabled=svc_data.get("enabled", False),
                    priority=svc_data.get("priority", 0),
                )
        return config

    @classmethod
    def __apply_env_overrides(cls, config: Configuration) -> Configuration:
        overrides = {
            "UNDERWRITE_BUS_BACKEND": ("bus", "backend"),
            "UNDERWRITE_BUS_RATE_LIMIT": ("bus", "rate_limit"),
            "UNDERWRITE_BUS_MAX_WORKERS": ("bus", "max_workers"),
            "UNDERWRITE_STORE_BACKEND": ("store", "backend"),
            "UNDERWRITE_STORE_DSN": ("store", "dsn"),
            "UNDERWRITE_STORE_POOL_SIZE": ("store", "pool_size"),
            "UNDERWRITE_STORE_READ_BACKEND": ("store", "read_backend"),
            "UNDERWRITE_STORE_READ_DSN": ("store", "read_dsn"),
            "UNDERWRITE_LOG_LEVEL": ("logging", "level"),
            "UNDERWRITE_LOG_OUTPUT": ("logging", "output"),
            "UNDERWRITE_LOG_FORMAT": ("logging", "log_format"),
            "UNDERWRITE_DATA_DIR": ("data_dir",),
            "UNDERWRITE_AUTHZ_ENABLED": ("authz", "enabled"),
            "UNDERWRITE_AUTHZ_POLICY_FILE": ("authz", "policy_file"),
            "UNDERWRITE_METRICS_ENABLED": ("metrics", "enabled"),
            "UNDERWRITE_METRICS_EXPORT_INTERVAL": ("metrics", "export_interval"),
            "UNDERWRITE_TRACING_ENABLED": ("tracing", "enabled"),
            "UNDERWRITE_TRACING_EXPORTER": ("tracing", "exporter"),
            "UNDERWRITE_SAGA_ENABLED": ("saga", "enabled"),
            "UNDERWRITE_IDENTITY_KEY_TTL": ("identity", "key_ttl"),
            "UNDERWRITE_IDENTITY_KEY_GRACE": ("identity", "key_grace"),
            "UNDERWRITE_SECRETS_BACKEND": ("secrets", "backend"),
            "UNDERWRITE_SECRETS_VAULT_URL": ("secrets", "url"),
            "UNDERWRITE_SECRETS_VAULT_TOKEN": ("secrets", "token"),
            "UNDERWRITE_SECRETS_AWS_REGION": ("secrets", "region"),
            "UNDERWRITE_RECOVERY_AUTO_RESTART": ("recovery", "auto_restart"),
            "UNDERWRITE_RECOVERY_MAX_RESTARTS": ("recovery", "max_restarts"),
            "UNDERWRITE_RECOVERY_BACKOFF": ("recovery", "backoff_seconds"),
        }
        for env_var, attrs in overrides.items():
            val = os.environ.get(env_var)
            if val is None:
                continue
            if len(attrs) == 1:
                setattr(config, attrs[0], val)
            else:
                section = getattr(config, attrs[0])
                setattr(section, attrs[1], val)
        return config


SERVICE_NAMES: list[str] = [
    "mechanism",
    "audit",
    "quote",
    "risk",
    "fraud",
    "compliance",
    "npa",
    "collateral",
    "recovery",
    "governance",
    "graph",
    "identity",
    "notification",
    "reporting",
    "underwriter",
    "pricing",
    "document",
    "disbursement",
    "collection",
    "settlement",
    "origination",
    "servicing",
    "payment",
    "communication",
    "workflow",
    "decision",
    "fee",
    "statement",
]
