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
    "AuditConfig",
    "BusConfig",
    "Configuration",
    "FeeConfig",
    "GovernanceConfig",
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
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from underwrite.__exceptions__ import ConfigurationError

logger = logging.getLogger(__name__)


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
    max_futures: int = 10000  # max pending futures before backpressure


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
class FeeConfig:
    """Fee schedule configuration.

    Each key is a fee type name; each value is the flat amount (for
    flat-rate fees) or the rate (for percentage-based fees like
    origination).
    """
    schedules: dict[str, float] = field(default_factory=lambda: {
        "late_payment": 25.0,
        "origination": 0.01,
        "prepayment": 0.005,
        "service": 5.0,
    })


@dataclass
class GovernanceConfig:
    """Governance parameter ranges and defaults configuration."""
    param_ranges: dict[str, list[float]] = field(default_factory=lambda: {
        "protocol_rate": [0.0, 1.0],
        "max_delegation_rate": [0.0, 1.0],
        "dlg_cap_ratio": [0.0, 1.0],
        "ltv_ratio": [0.0, 1.0],
        "min_base_budget": [0.0, 1e18],
    })
    param_defaults: dict[str, float] = field(default_factory=lambda: {
        "protocol_rate": 0.10,
        "max_delegation_rate": 0.05,
        "dlg_cap_ratio": 0.05,
        "ltv_ratio": 0.75,
        "min_base_budget": 1000.0,
    })


@dataclass
class AuditConfig:
    """Audit service configuration."""
    max_ledger: int = 100000
    export_url: str = ""


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
    fee: FeeConfig = field(default_factory=FeeConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)

    @classmethod
    def default(cls) -> Configuration:
        """Returns a default configuration with all services listed but disabled."""
        config = Configuration()
        config.store.backend = "filesystem"
        for service_name in SERVICE_NAMES:
            config.services[service_name] = ServiceConfig(enabled=False)
        return config

    _SCHEMA_CACHE: dict[str, Any] | None = None

    @classmethod
    def _schema(cls) -> dict[str, Any]:
        """Return a JSON Schema dict for validating loaded configuration.

        The schema is built once and cached as a class-level attribute.
        """
        if cls._SCHEMA_CACHE is not None:
            return cls._SCHEMA_CACHE
        cls._SCHEMA_CACHE = {
            "type": "object",
            "properties": {
                "bus": {
                    "type": "object",
                    "properties": {
                        "backend": {"type": "string", "enum": ["local", "sqs", "modal"]},
                        "rate_limit": {"type": "number", "minimum": 0},
                        "max_workers": {"type": "integer", "minimum": 0},
                        "max_futures": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
                "store": {
                    "type": "object",
                    "properties": {
                        "backend": {"type": "string", "enum": ["memory", "filesystem", "postgres"]},
                        "dsn": {"type": "string"},
                        "pool_size": {"type": "integer", "minimum": 1},
                        "read_backend": {"type": "string"},
                        "read_dsn": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "logging": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
                        "output": {"type": "string"},
                        "format": {"type": "string", "enum": ["text", "json"]},
                    },
                    "additionalProperties": False,
                },
                "identity": {
                    "type": "object",
                    "properties": {
                        "public_key": {"type": "string"},
                        "key_ttl": {"type": "number", "minimum": 0},
                        "key_grace": {"type": "number", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "authz": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "policy_file": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "metrics": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "export_interval": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "migration": {
                    "type": "object",
                    "properties": {
                        "auto_migrate": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "tracing": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "exporter": {"type": "string", "enum": ["console", "otlp", "noop"]},
                    },
                    "additionalProperties": False,
                },
                "saga": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "services": {
                    "type": "object",
                    "patternProperties": {
                        "^[a-z_]+$": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "priority": {"type": "integer"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                "secrets": {
                    "type": "object",
                    "properties": {
                        "backend": {"type": "string"},
                        "url": {"type": "string"},
                        "token": {"type": "string"},
                        "region": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "recovery": {
                    "type": "object",
                    "properties": {
                        "auto_restart": {"type": "boolean"},
                        "max_restarts": {"type": "integer", "minimum": 0},
                        "backoff_seconds": {"type": "number", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "fee": {
                    "type": "object",
                    "properties": {
                        "schedules": {
                            "type": "object",
                            "patternProperties": {
                                "^[a-z_]+$": {"type": "number"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                "governance": {
                    "type": "object",
                    "properties": {
                        "param_ranges": {
                            "type": "object",
                            "patternProperties": {
                                "^[a-z_]+$": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "minItems": 2,
                                    "maxItems": 2,
                                },
                            },
                            "additionalProperties": False,
                        },
                        "param_defaults": {
                            "type": "object",
                            "patternProperties": {
                                "^[a-z_]+$": {"type": "number"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                "audit": {
                    "type": "object",
                    "properties": {
                        "max_ledger": {"type": "integer", "minimum": 1},
                        "export_url": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "data_dir": {"type": "string"},
            },
            "additionalProperties": False,
        }
        return cls._SCHEMA_CACHE

    @classmethod
    def _validate(cls, data: dict[str, Any]) -> None:
        """Validate a parsed config dict against the JSON Schema.

        Args:
            data: Parsed JSON config data.

        Raises:
            ConfigurationError: If validation fails with details about
                which field is invalid and what was expected.
        """
        schema = cls._schema()
        errors: list[str] = []

        def _validate_value(value: Any, schema_node: dict[str, Any],
                            path: str) -> None:
            if "enum" in schema_node:
                if value not in schema_node["enum"]:
                    errors.append(
                        f"{path}: expected one of {schema_node['enum']!r}, got {value!r}"
                    )
            if schema_node.get("type") == "string":
                if not isinstance(value, str):
                    errors.append(
                        f"{path}: expected string, got {type(value).__name__}")
            elif schema_node.get("type") == "number":
                if not isinstance(value, (int, float)):
                    errors.append(
                        f"{path}: expected number, got {type(value).__name__}")
                elif isinstance(value, (int, float)):
                    if "minimum" in schema_node and value < schema_node["minimum"]:
                        errors.append(
                            f"{path}: value {value} is below minimum {schema_node['minimum']}"
                        )
            elif schema_node.get("type") == "integer":
                if not isinstance(value, int):
                    errors.append(
                        f"{path}: expected integer, got {type(value).__name__}")
                elif "minimum" in schema_node and value < schema_node["minimum"]:
                    errors.append(
                        f"{path}: value {value} is below minimum {schema_node['minimum']}"
                    )
            elif schema_node.get("type") == "boolean":
                if not isinstance(value, bool):
                    errors.append(
                        f"{path}: expected boolean, got {type(value).__name__}")

        def _walk(data_node: Any, schema_node: dict[str, Any],
                  path: str) -> None:
            if "properties" in schema_node:
                if not isinstance(data_node, dict):
                    errors.append(
                        f"{path}: expected object, got {type(data_node).__name__}")
                    return
                if schema_node.get("additionalProperties") is False:
                    extra = set(data_node.keys()) - set(
                        schema_node.get("properties", {}).keys())
                    for k in sorted(extra):
                        errors.append(
                            f"{path}.{k}: unknown field (not in schema)")
                for key, prop_schema in schema_node.get("properties",
                                                         {}).items():
                    if key in data_node:
                        _walk(data_node[key], prop_schema,
                              f"{path}.{key}" if path else key)
            elif "patternProperties" in schema_node:
                if not isinstance(data_node, dict):
                    errors.append(
                        f"{path}: expected object, got {type(data_node).__name__}")
                    return
                if schema_node.get("additionalProperties") is False:
                    for k in data_node:
                        matched = any(k.startswith(p.rstrip("$")) for p in
                                      schema_node.get("patternProperties", {}))
                        if not matched and not any(
                                True for p in schema_node.get(
                                    "patternProperties", {})
                                if __import__("re").match(p, k)):
                            errors.append(
                                f"{path}.{k}: unknown service name")
                for key, value in data_node.items():
                    for pattern, prop_schema in schema_node.get(
                            "patternProperties", {}).items():
                        if __import__("re").match(pattern, key):
                            _walk(value, prop_schema,
                                  f"{path}.{key}" if path else key)
                            break
            elif "type" in schema_node:
                _validate_value(data_node, schema_node, path)

        _walk(data, schema, "")
        if errors:
            raise ConfigurationError(
                "Configuration validation failed:\n" + "\n".join(errors))

    @classmethod
    def load(cls, path: str | None = None) -> Configuration:
        """Loads configuration from a JSON file, env vars, or returns defaults."""
        config = cls.default()
        env = os.environ.get("UNDERWRITE_ENV", "")
        # Try env-specific config files first
        for candidate in ([path] if path else []):
            if candidate and Path(candidate).exists():
                try:
                    with open(candidate) as fh:
                        data = json.load(fh)
                except (FileNotFoundError, json.JSONDecodeError) as exc:
                    logger.warning("failed to load config %s: %s", candidate, exc)
                    continue
                if not isinstance(data, dict):
                    raise ConfigurationError("config root must be a JSON object")
                cls._validate(data)
                config = cls.__merge(config, data)
                break
        else:
            # Try UNDERWRITE_ENV-specific file
            if env:
                env_path = f"config.{env}.json"
                if Path(env_path).exists():
                    try:
                        with open(env_path) as fh:
                            data = json.load(fh)
                    except (FileNotFoundError, json.JSONDecodeError) as exc:
                        logger.warning("failed to load env config %s: %s",
                                       env_path, exc)
                    else:
                        if not isinstance(data, dict):
                            raise ConfigurationError("config root must be a JSON object")
                        cls._validate(data)
                        config = cls.__merge(config, data)
        config = cls.__apply_env_overrides(config)
        return config

    def save(self, path: str) -> None:
        """Persists configuration to a JSON file after schema validation."""
        data = self.to_dict()
        self._validate(data)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)

    def to_dict(self) -> dict[str, Any]:
        """Serialises configuration to a dictionary."""
        return {
            "bus": {
                "backend": self.bus.backend,
                "rate_limit": self.bus.rate_limit,
                "max_workers": self.bus.max_workers,
                "max_futures": self.bus.max_futures,
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
                "key_grace": self.identity.key_grace,
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
            "fee": {
                "schedules": dict(self.fee.schedules),
            },
            "governance": {
                "param_ranges": {k: list(v) for k, v in self.governance.param_ranges.items()},
                "param_defaults": dict(self.governance.param_defaults),
            },
            "audit": {
                "max_ledger": self.audit.max_ledger,
                "export_url": self.audit.export_url,
            },
            "data_dir": self.data_dir,
        }

    def enabled_services(self) -> list[str]:
        """Returns the list of enabled service names."""
        return [name for name, svc in self.services.items() if svc.enabled]

    @classmethod
    def __merge(cls, config: Configuration, data: dict[str,
                                                        Any]) -> Configuration:
        import copy
        config = copy.deepcopy(config)
        known_keys = {
            "bus", "store", "logging", "identity", "data_dir", "services",
            "authz", "metrics", "migration", "tracing", "saga", "secrets",
            "recovery", "fee", "governance", "audit",
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
            config.bus.max_futures = data["bus"].get("max_futures",
                                                     config.bus.max_futures)
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
            # private_key must NOT be loaded from JSON config; only
            # from env vars or a secrets backend.
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
            # token must NOT be loaded from JSON; only from env vars
            config.secrets.region = data["secrets"].get("region", config.secrets.region)
        if "recovery" in data:
            config.recovery.auto_restart = data["recovery"].get("auto_restart", config.recovery.auto_restart)
            config.recovery.max_restarts = data["recovery"].get("max_restarts", config.recovery.max_restarts)
            config.recovery.backoff_seconds = data["recovery"].get("backoff_seconds", config.recovery.backoff_seconds)
        if "fee" in data:
            schedules = data["fee"].get("schedules")
            if schedules is not None and isinstance(schedules, dict):
                config.fee.schedules.update(schedules)
        if "governance" in data:
            ranges = data["governance"].get("param_ranges")
            if ranges is not None and isinstance(ranges, dict):
                for k, v in ranges.items():
                    if isinstance(v, (list, tuple)) and len(v) == 2:
                        config.governance.param_ranges[k] = [float(v[0]), float(v[1])]
            defaults = data["governance"].get("param_defaults")
            if defaults is not None and isinstance(defaults, dict):
                config.governance.param_defaults.update(defaults)
        if "audit" in data:
            audit_data = data["audit"]
            if isinstance(audit_data, dict):
                if "max_ledger" in audit_data:
                    config.audit.max_ledger = int(audit_data["max_ledger"])
                if "export_url" in audit_data:
                    config.audit.export_url = str(audit_data["export_url"])
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
            "UNDERWRITE_BUS_BACKEND": ("bus", "backend", str),
            "UNDERWRITE_BUS_RATE_LIMIT": ("bus", "rate_limit", float),
            "UNDERWRITE_BUS_MAX_WORKERS": ("bus", "max_workers", int),
            "UNDERWRITE_BUS_MAX_FUTURES": ("bus", "max_futures", int),
            "UNDERWRITE_STORE_BACKEND": ("store", "backend", str),
            "UNDERWRITE_STORE_DSN": ("store", "dsn", str),
            "UNDERWRITE_STORE_POOL_SIZE": ("store", "pool_size", int),
            "UNDERWRITE_STORE_READ_BACKEND": ("store", "read_backend", str),
            "UNDERWRITE_STORE_READ_DSN": ("store", "read_dsn", str),
            "UNDERWRITE_LOG_LEVEL": ("logging", "level", str),
            "UNDERWRITE_LOG_OUTPUT": ("logging", "output", str),
            "UNDERWRITE_LOG_FORMAT": ("logging", "log_format", str),
            "UNDERWRITE_DATA_DIR": ("data_dir", None, str),
            "UNDERWRITE_AUTHZ_ENABLED": ("authz", "enabled", bool),
            "UNDERWRITE_AUTHZ_POLICY_FILE": ("authz", "policy_file", str),
            "UNDERWRITE_METRICS_ENABLED": ("metrics", "enabled", bool),
            "UNDERWRITE_METRICS_EXPORT_INTERVAL": ("metrics", "export_interval", int),
            "UNDERWRITE_TRACING_ENABLED": ("tracing", "enabled", bool),
            "UNDERWRITE_TRACING_EXPORTER": ("tracing", "exporter", str),
            "UNDERWRITE_SAGA_ENABLED": ("saga", "enabled", bool),
            "UNDERWRITE_IDENTITY_KEY_TTL": ("identity", "key_ttl", float),
            "UNDERWRITE_IDENTITY_KEY_GRACE": ("identity", "key_grace", float),
            "UNDERWRITE_SECRETS_BACKEND": ("secrets", "backend", str),
            "UNDERWRITE_SECRETS_VAULT_URL": ("secrets", "url", str),
            "UNDERWRITE_SECRETS_VAULT_TOKEN": ("secrets", "token", str),
            "UNDERWRITE_SECRETS_AWS_REGION": ("secrets", "region", str),
            "UNDERWRITE_RECOVERY_AUTO_RESTART": ("recovery", "auto_restart", bool),
            "UNDERWRITE_RECOVERY_MAX_RESTARTS": ("recovery", "max_restarts", int),
            "UNDERWRITE_RECOVERY_BACKOFF": ("recovery", "backoff_seconds", float),
            "UNDERWRITE_AUDIT_MAX_LEDGER": ("audit", "max_ledger", int),
            "UNDERWRITE_AUDIT_EXPORT_URL": ("audit", "export_url", str),
        }
        for env_var, (section_attr, field_attr, typ) in overrides.items():
            val = os.environ.get(env_var)
            if val is None:
                continue
            try:
                if typ is bool:
                    coerced = val.lower() in ("1", "true", "yes")
                else:
                    coerced = typ(val)
            except (ValueError, TypeError):
                logger.warning("failed to coerce %s=%r to %s, skipping", env_var, val, typ.__name__)
                continue
            if field_attr is None:
                setattr(config, section_attr, coerced)
            else:
                section = getattr(config, section_attr)
                setattr(section, field_attr, coerced)
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
