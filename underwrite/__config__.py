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
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from underwrite.__exceptions__ import ConfigurationError

logger = logging.getLogger(__name__)


class _ForbidExtra(BaseModel):
    model_config = {"extra": "forbid"}


class ServiceConfig(_ForbidExtra):
    enabled: bool = False
    priority: int = 0


_BACKENDS = Annotated[str, Field(validate_default=True)]


class BusConfig(_ForbidExtra):
    backend: str = "local"
    rate_limit: float = Field(default=0.0, ge=0)
    max_workers: int = Field(default=0, ge=0)
    max_futures: int = Field(default=10000, ge=1)

    @field_validator("backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        allowed = {"local", "sqs", "modal"}
        if v not in allowed:
            raise ValueError(f"bus.backend must be one of {allowed}, got {v!r}")
        return v


class StoreConfig(_ForbidExtra):
    backend: str = "memory"
    dsn: str = ""
    pool_size: int = Field(default=5, ge=1)
    read_backend: str = ""
    read_dsn: str = ""

    @field_validator("backend")
    @classmethod
    def _check_backend(cls, v: str) -> str:
        allowed = {"memory", "filesystem", "postgres"}
        if v not in allowed:
            raise ValueError(
                f"store.backend must be one of {allowed}, got {v!r}")
        return v


class LoggingConfig(_ForbidExtra):
    level: str = "INFO"
    output: str = "stdout"
    log_format: str = "text"

    @field_validator("level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in allowed:
            raise ValueError(
                f"logging.level must be one of {allowed}, got {v!r}")
        return v

    @field_validator("log_format")
    @classmethod
    def _check_format(cls, v: str) -> str:
        allowed = {"text", "json"}
        if v not in allowed:
            raise ValueError(
                f"logging.log_format must be one of {allowed}, got {v!r}")
        return v


class IdentityConfig(_ForbidExtra):
    private_key: str = ""
    public_key: str = ""
    key_ttl: float = Field(default=86400.0, ge=0)
    key_grace: float = Field(default=3600.0, ge=0)


class AuthzConfig(_ForbidExtra):
    enabled: bool = False
    policy_file: str = ""


class MetricsConfig(_ForbidExtra):
    enabled: bool = True
    export_interval: int = Field(default=60, ge=0)


class MigrationConfig(_ForbidExtra):
    auto_migrate: bool = True


class TracingConfig(_ForbidExtra):
    enabled: bool = False
    exporter: str = "console"

    @field_validator("exporter")
    @classmethod
    def _check_exporter(cls, v: str) -> str:
        allowed = {"console", "otlp", "noop"}
        if v not in allowed:
            raise ValueError(
                f"tracing.exporter must be one of {allowed}, got {v!r}")
        return v


class SagaConfig(_ForbidExtra):
    enabled: bool = True


class SecretsConfig(_ForbidExtra):
    backend: str = "env"
    url: str = ""
    token: str = ""
    region: str = ""


class RecoveryConfig(_ForbidExtra):
    auto_restart: bool = True
    max_restarts: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=1.0, ge=0)


class FeeConfig(_ForbidExtra):
    schedules: dict[str, float] = Field(
        default_factory=lambda: {
            "late_payment": 25.0,
            "origination": 0.01,
            "prepayment": 0.005,
            "service": 5.0,
        })


class GovernanceConfig(_ForbidExtra):
    param_ranges: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "protocol_rate": [0.0, 1.0],
            "max_delegation_rate": [0.0, 1.0],
            "dlg_cap_ratio": [0.0, 1.0],
            "ltv_ratio": [0.0, 1.0],
            "min_base_budget": [0.0, 1e18],
        })
    param_defaults: dict[str, float] = Field(
        default_factory=lambda: {
            "protocol_rate": 0.10,
            "max_delegation_rate": 0.05,
            "dlg_cap_ratio": 0.05,
            "ltv_ratio": 0.75,
            "min_base_budget": 1000.0,
        })


class AuditConfig(_ForbidExtra):
    max_ledger: int = Field(default=100000, ge=1)
    export_url: str = ""


class Configuration(_ForbidExtra):
    bus: BusConfig = Field(default_factory=BusConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    authz: AuthzConfig = Field(default_factory=AuthzConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    migration: MigrationConfig = Field(default_factory=MigrationConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    saga: SagaConfig = Field(default_factory=SagaConfig)
    services: dict[str, ServiceConfig] = Field(default_factory=dict)
    data_dir: str = "./data"
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    fee: FeeConfig = Field(default_factory=FeeConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    @classmethod
    def default(cls) -> Configuration:
        config = Configuration()
        config.store.backend = "filesystem"
        for service_name in SERVICE_NAMES:
            config.services[service_name] = ServiceConfig(enabled=False)
        return config

    @classmethod
    def load(cls, path: str | None = None) -> Configuration:
        config = cls.default()
        env = os.environ.get("UNDERWRITE_ENV", "")
        for candidate in ([path] if path else []):
            if candidate and Path(candidate).exists():
                try:
                    with open(candidate) as fh:
                        data = json.load(fh)
                except (FileNotFoundError, json.JSONDecodeError) as exc:
                    logger.warning("failed to load config %s: %s", candidate,
                                   exc)
                    continue
                if not isinstance(data, dict):
                    raise ConfigurationError(
                        "config root must be a JSON object")
                config = cls.__merge(config, data)
                break
        else:
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
                            raise ConfigurationError(
                                "config root must be a JSON object")
                        config = cls.__merge(config, data)
        config = cls.__apply_env_overrides(config)
        return config

    def save(self, path: str) -> None:
        data = self.model_dump(exclude_none=True)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump(exclude_none=True)
        if "secrets" in d:
            d["secrets"].pop("token", None)
            if not d["secrets"]:
                d.pop("secrets")
        if "identity" in d:
            d["identity"].pop("private_key", None)
        return d

    def enabled_services(self) -> list[str]:
        return [name for name, svc in self.services.items() if svc.enabled]

    @classmethod
    def __merge(cls, config: Configuration, data: dict[str,
                                                       Any]) -> Configuration:
        import copy

        config = copy.deepcopy(config)
        known_keys = {
            "bus",
            "store",
            "logging",
            "identity",
            "data_dir",
            "services",
            "authz",
            "metrics",
            "migration",
            "tracing",
            "saga",
            "secrets",
            "recovery",
            "fee",
            "governance",
            "audit",
        }
        unknown = set(data.keys()) - known_keys
        if unknown:
            raise ConfigurationError(
                f"unknown config keys: {', '.join(sorted(unknown))}")

        def _merge_sub(model_cls, section, cfg, data_map):
            unknown = set(data_map) - set(model_cls.model_fields)
            if unknown:
                raise ConfigurationError(
                    f"{section}: unknown field(s): {', '.join(sorted(unknown))}"
                )
            from pydantic import ValidationError
            merged = cfg.model_copy(update={
                k: v for k, v in data_map.items() if k in model_cls.model_fields
            })
            try:
                return model_cls(**merged.model_dump())
            except ValidationError as exc:
                msg = "; ".join(
                    f"{section}.{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                    for e in exc.errors())
                raise ConfigurationError(msg) from exc

        if "bus" in data:
            config.bus = _merge_sub(BusConfig, "bus", config.bus, data["bus"])
        if "store" in data:
            config.store = _merge_sub(StoreConfig, "store", config.store,
                                      data["store"])
        if "logging" in data:
            overrides = dict(data["logging"])
            if "format" in overrides and "log_format" not in overrides:
                overrides["log_format"] = overrides.pop("format")
            config.logging = _merge_sub(LoggingConfig, "logging",
                                        config.logging, overrides)
        if "identity" in data:
            config.identity = _merge_sub(IdentityConfig, "identity",
                                         config.identity, data["identity"])
        if "authz" in data:
            config.authz = _merge_sub(AuthzConfig, "authz", config.authz,
                                      data["authz"])
        if "metrics" in data:
            config.metrics = _merge_sub(MetricsConfig, "metrics",
                                        config.metrics, data["metrics"])
        if "migration" in data:
            config.migration = _merge_sub(MigrationConfig, "migration",
                                          config.migration, data["migration"])
        if "tracing" in data:
            config.tracing = _merge_sub(TracingConfig, "tracing",
                                        config.tracing, data["tracing"])
        if "saga" in data:
            config.saga = _merge_sub(SagaConfig, "saga", config.saga,
                                     data["saga"])
        if "secrets" in data:
            config.secrets = _merge_sub(SecretsConfig, "secrets",
                                        config.secrets, data["secrets"])
        if "recovery" in data:
            config.recovery = _merge_sub(RecoveryConfig, "recovery",
                                         config.recovery, data["recovery"])
        if "fee" in data:
            schedules = data["fee"].get("schedules")
            if schedules is not None and isinstance(schedules, dict):
                config.fee.schedules.update(schedules)
        if "governance" in data:
            ranges = data["governance"].get("param_ranges")
            if ranges is not None and isinstance(ranges, dict):
                for k, v in ranges.items():
                    if isinstance(v, (list, tuple)) and len(v) == 2:
                        config.governance.param_ranges[k] = [
                            float(v[0]), float(v[1])
                        ]
            defaults = data["governance"].get("param_defaults")
            if defaults is not None and isinstance(defaults, dict):
                config.governance.param_defaults.update(defaults)
        if "audit" in data:
            config.audit = config.audit.model_copy(update=dict(
                (k, data["audit"][k])
                for k in data["audit"]
                if k in AuditConfig.model_fields))
        if "data_dir" in data:
            config.data_dir = data["data_dir"]
        if "services" in data:
            config.services.clear()
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
            "UNDERWRITE_METRICS_EXPORT_INTERVAL":
                ("metrics", "export_interval", int),
            "UNDERWRITE_TRACING_ENABLED": ("tracing", "enabled", bool),
            "UNDERWRITE_TRACING_EXPORTER": ("tracing", "exporter", str),
            "UNDERWRITE_SAGA_ENABLED": ("saga", "enabled", bool),
            "UNDERWRITE_IDENTITY_KEY_TTL": ("identity", "key_ttl", float),
            "UNDERWRITE_IDENTITY_KEY_GRACE": ("identity", "key_grace", float),
            "UNDERWRITE_SECRETS_BACKEND": ("secrets", "backend", str),
            "UNDERWRITE_SECRETS_VAULT_URL": ("secrets", "url", str),
            "UNDERWRITE_SECRETS_VAULT_TOKEN": ("secrets", "token", str),
            "UNDERWRITE_SECRETS_AWS_REGION": ("secrets", "region", str),
            "UNDERWRITE_RECOVERY_AUTO_RESTART":
                ("recovery", "auto_restart", bool),
            "UNDERWRITE_RECOVERY_MAX_RESTARTS":
                ("recovery", "max_restarts", int),
            "UNDERWRITE_RECOVERY_BACKOFF":
                ("recovery", "backoff_seconds", float),
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
                logger.warning("failed to coerce %s=%r to %s, skipping",
                               env_var, val, typ.__name__)
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
