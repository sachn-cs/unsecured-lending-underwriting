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
    "ConsentConfig",
    "CreditBureauConfig",
    "DpdpaConfig",
    "DsrConfig",
    "FeeConfig",
    "GovernanceConfig",
    "IdentityConfig",
    "KfsConfig",
    "LoggingConfig",
    "MetricsConfig",
    "MigrationConfig",
    "NpaConfig",
    "RazorpayConfig",
    "RecoveryConfig",
    "SagaConfig",
    "SecretsConfig",
    "SERVICE_NAMES",
    "ServiceConfig",
    "StoreConfig",
    "TracingConfig",
    "UnderwritingConfig",
]

import json
import os
from pathlib import Path
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, Field, field_validator

from underwrite.__exceptions__ import ConfigurationError
from underwrite.__logger__ import logger
from underwrite.services.kyc_providers.factory import KycProviderConfig

ModelT = TypeVar("ModelT", bound=BaseModel)


class ForbidExtra(BaseModel):
    """Base model that rejects unknown fields on instantiation."""

    model_config = {"extra": "forbid"}


class ServiceConfig(ForbidExtra):
    """Per-service enable/disable and priority assignment."""

    enabled: bool = False
    priority: int = 0


BACKENDS = Annotated[str, Field(validate_default=True)]


class BusConfig(ForbidExtra):
    """Configuration for the event bus backend (local, sqs, or modal)."""

    backend: str = "local"
    rate_limit: float = Field(default=0.0, ge=0)
    max_workers: int = Field(default=0, ge=0)
    max_futures: int = Field(default=10000, ge=1)
    sqs_queue_url: str = ""
    sqs_region: str = ""
    modal_queue_name: str = "underwrite-bus"

    @field_validator("backend")
    @classmethod
    def check_backend(cls, v: str) -> str:
        allowed = {"local", "sqs", "modal"}
        if v not in allowed:
            raise ValueError(f"bus.backend must be one of {allowed}, got {v!r}")
        return v


class StoreConfig(ForbidExtra):
    """Configuration for the persistence store (memory, filesystem, or postgres)."""

    backend: str = "memory"
    dsn: str = ""
    pool_size: int = Field(default=5, ge=1)
    read_backend: str = ""
    read_dsn: str = ""
    data_residency: str = "india"  # "india" or "global" - restricts data storage to Indian regions

    @field_validator("backend")
    @classmethod
    def check_backend(cls, v: str) -> str:
        allowed = {"memory", "filesystem", "postgres"}
        if v not in allowed:
            raise ValueError(f"store.backend must be one of {allowed}, got {v!r}")
        return v


class LoggingConfig(ForbidExtra):
    """Configuration for logging level, output destination, and format."""

    level: str = "INFO"
    output: str = "stdout"
    log_format: str = "text"

    @field_validator("level")
    @classmethod
    def check_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in allowed:
            raise ValueError(f"logging.level must be one of {allowed}, got {v!r}")
        return v

    @field_validator("log_format")
    @classmethod
    def check_format(cls, v: str) -> str:
        allowed = {"text", "json"}
        if v not in allowed:
            raise ValueError(f"logging.log_format must be one of {allowed}, got {v!r}")
        return v


class IdentityConfig(ForbidExtra):
    """Cryptographic identity settings — keys, passphrase, and TTL."""

    private_key: str = ""
    public_key: str = ""
    encryption_passphrase: str = ""
    key_ttl: float = Field(default=86400.0, ge=0)
    key_grace: float = Field(default=3600.0, ge=0)


class AuthzConfig(ForbidExtra):
    """Authorization policy settings."""

    enabled: bool = True
    policy_file: str = ""


class MetricsConfig(ForbidExtra):
    """Prometheus-style metrics export configuration."""

    enabled: bool = True
    export_interval: int = Field(default=60, ge=0)


class MigrationConfig(ForbidExtra):
    """Schema migration behaviour."""

    auto_migrate: bool = True


class TracingConfig(ForbidExtra):
    """Distributed tracing configuration (console, otlp, or noop)."""

    enabled: bool = False
    exporter: str = "console"

    @field_validator("exporter")
    @classmethod
    def check_exporter(cls, v: str) -> str:
        allowed = {"console", "otlp", "noop"}
        if v not in allowed:
            raise ValueError(f"tracing.exporter must be one of {allowed}, got {v!r}")
        return v


class SagaConfig(ForbidExtra):
    """Saga orchestration settings."""

    enabled: bool = True


class SecretsConfig(ForbidExtra):
    """Secrets backend configuration (env, vault, or aws)."""

    backend: str = "env"
    url: str = ""
    token: str = ""
    region: str = ""


class RecoveryConfig(ForbidExtra):
    """Service auto-recovery and restart back-off settings."""

    auto_restart: bool = True
    max_restarts: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=1.0, ge=0)


class FeeConfig(ForbidExtra):
    """Fee schedules for late payment, origination, prepayment, and service fees."""

    schedules: dict[str, float] = Field(
        default_factory=lambda: {
            "late_payment": 25.0,
            "origination": 0.01,
            "prepayment": 0.005,
            "service": 5.0,
        }
    )
    penal_interest_daily_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    late_payment_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    max_penal_interest_per_loan: float = Field(default=0.0, ge=0.0)


class KfsConfig(ForbidExtra):
    """KFS (Key Fact Statement) configuration per RBI guidelines."""

    enabled: bool = Field(default=True)
    template_dir: str = ""
    annual_interest_rate_disclosure: str = "annual_reducing"
    include_foreclosure_terms: bool = Field(default=True)
    include_late_fee_disclosure: bool = Field(default=True)


class NpaConfig(ForbidExtra):
    """NPA asset classification and provisioning configuration per RBI norms.

    Covers SMA (Special Mention Account) triggers, provisioning
    percentages per bucket, and DLG (Debt Liquidation Guarantee)
    threshold.
    """

    standard_provisioning_rate: float = Field(default=0.0025, ge=0.0, le=1.0)
    substandard_provisioning_rate: float = Field(default=0.15, ge=0.0, le=1.0)
    doubtful_provisioning_rate_secured: float = Field(default=0.25, ge=0.0, le=1.0)
    loss_provisioning_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    sma_0_days: int = Field(default=30, ge=1)
    sma_1_days: int = Field(default=60, ge=1)
    sma_2_days: int = Field(default=90, ge=1)
    npa_days: int = Field(default=90, ge=1)
    dlg_trigger_days: int = Field(default=120, ge=1)


class ConsentConfig(ForbidExtra):
    """Consent management configuration per DPDPA 2023."""

    required_purposes: list[str] = Field(
        default_factory=lambda: [
            "kyc_verification",
            "credit_bureau_reporting",
            "loan_servicing",
            "collection",
            "communication_transactional",
        ]
    )
    consent_validity_days: int = Field(default=365, ge=1)
    withdrawal_cooldown_days: int = Field(default=0, ge=0)


class DsrConfig(ForbidExtra):
    """Data Subject Rights configuration per DPDPA 2023."""

    response_time_days: int = Field(default=30, ge=1)
    grievance_response_days: int = Field(default=15, ge=1)
    dpo_email: str = ""
    dpo_phone: str = ""


class DpdpaConfig(ForbidExtra):
    """Top-level DPDPA 2023 (India) data protection configuration."""

    consent: ConsentConfig = Field(default_factory=ConsentConfig)
    dsr: DsrConfig = Field(default_factory=DsrConfig)
    data_retention_years: int = Field(default=8, ge=1)
    kyc_retention_years: int = Field(default=5, ge=1)
    breach_notification_hours: int = Field(default=72, ge=1)
    enable_breach_detection: bool = Field(default=True)
    enable_auto_purge: bool = Field(default=False)


class RazorpayConfig(ForbidExtra):
    """Razorpay payment gateway configuration.

    Supports UPI Autopay and e-NACH mandate collection
    for recurring payments.  All keys are loaded from
    environment variables or secrets backend in production.
    """

    key_id: str = ""
    key_secret: str = ""
    webhook_secret: str = ""
    api_base_url: str = "https://api.razorpay.com/v1"
    payment_link_enabled: bool = Field(default=True)
    subscription_enabled: bool = Field(default=True)
    upi_autopay_enabled: bool = Field(default=True)
    enable_nach: bool = Field(default=True)
    max_retry_count: int = Field(default=3, ge=0)
    retry_delay_seconds: int = Field(default=5, ge=1)
    payment_timeout_minutes: int = Field(default=30, ge=1)
    capture_enabled: bool = Field(default=True)


class UnderwritingConfig(ForbidExtra):
    """Underwriting engine configuration — rules, thresholds, and policies."""

    max_default_probability: float = Field(default=0.25, ge=0.0, le=1.0)
    min_credit_score: int = Field(default=650, ge=300, le=900)
    max_dti_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    max_ltv_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    max_principal: float = Field(default=10_000_000, ge=0)
    min_principal: float = Field(default=1_000, ge=0)
    max_tenor_months: int = Field(default=360, ge=1)
    policy_file: str = ""
    enable_auto_decision: bool = True


class CreditBureauConfig(ForbidExtra):
    """Credit bureau and CKYC configuration.

    Supports CIBIL, Experian, Equifax for credit reports and
    the CKYC registry for identity verification.
    """

    cibil_enabled: bool = Field(default=True)
    cibil_api_key: str = ""
    cibil_api_base: str = "https://api.cibil.com/v1"
    experian_enabled: bool = Field(default=False)
    experian_api_key: str = ""
    experian_api_base: str = "https://api.experian.in/v1"
    equifax_enabled: bool = Field(default=False)
    equifax_api_key: str = ""
    equifax_api_base: str = "https://api.equifax.com/in/v1"
    ckyc_enabled: bool = Field(default=True)
    ckyc_api_key: str = ""
    ckyc_api_base: str = "https://api.ckycindia.in/v1"
    timeout_seconds: int = Field(default=30, ge=1)


class GovernanceConfig(ForbidExtra):
    """Protocol governance parameter ranges and defaults."""

    param_ranges: dict[str, list[float]] = Field(
        default_factory=lambda: {
            "protocol_rate": [0.0, 1.0],
            "max_delegation_rate": [0.0, 1.0],
            "dlg_cap_ratio": [0.0, 1.0],
            "ltv_ratio": [0.0, 1.0],
            "min_base_budget": [0.0, 1e18],
        }
    )
    param_defaults: dict[str, float] = Field(
        default_factory=lambda: {
            "protocol_rate": 0.10,
            "max_delegation_rate": 0.05,
            "dlg_cap_ratio": 0.05,
            "ltv_ratio": 0.75,
            "min_base_budget": 1000.0,
        }
    )


class AuditConfig(ForbidExtra):
    """Audit ledger capacity and remote export URL."""

    max_ledger: int = Field(default=100000, ge=1)
    export_url: str = ""


class Configuration(ForbidExtra):
    """Top-level configuration for the underwrite platform.

    Aggregates all sub-configs (bus, store, logging, identity, etc.) and
    provides load/save/merge logic driven by JSON files and env vars.
    """

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
    data_dir: str = Field(default="./data")

    @field_validator("data_dir")
    @classmethod
    def _validate_data_dir(cls, v: str) -> str:
        if not v or "\x00" in v:
            raise ValueError(f"invalid data_dir: {v!r}")
        from pathlib import Path

        path = Path(v)
        # Reject obvious foot-guns: /etc, /, /proc, /sys. The path
        # is still used to read/write files so the operator must
        # explicitly opt in to such locations.
        parts = path.parts
        if parts and parts[0] == "/":
            dangerous = {"/", "/etc", "/proc", "/sys", "/var", "/usr"}
            if str(path) in dangerous or str(path).startswith(tuple(p + "/" for p in dangerous)):
                raise ValueError(f"data_dir {v!r} points at a sensitive system path")
        return v

    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    fee: FeeConfig = Field(default_factory=FeeConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    kfs: KfsConfig = Field(default_factory=KfsConfig)
    npa: NpaConfig = Field(default_factory=NpaConfig)
    dpdpa: DpdpaConfig = Field(default_factory=DpdpaConfig)
    razorpay: RazorpayConfig = Field(default_factory=RazorpayConfig)
    credit_bureau: CreditBureauConfig = Field(default_factory=CreditBureauConfig)
    underwriting: UnderwritingConfig = Field(default_factory=UnderwritingConfig)
    kyc_providers: KycProviderConfig = Field(default_factory=KycProviderConfig)

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
        for candidate in [path] if path else []:
            if candidate and ".." in Path(candidate).parts:
                raise ConfigurationError(f"config path traversal detected: {candidate}")
            if candidate and Path(candidate).exists():
                try:
                    with open(candidate) as fh:
                        data = json.load(fh)
                except (FileNotFoundError, json.JSONDecodeError) as exc:
                    logger.warning("failed to load config %s: %s", candidate, exc)
                    continue
                if not isinstance(data, dict):
                    raise ConfigurationError("config root must be a JSON object")
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
                        logger.warning("failed to load env config %s: %s", env_path, exc)
                    else:
                        if not isinstance(data, dict):
                            raise ConfigurationError("config root must be a JSON object")
                        config = cls.__merge(config, data)
        config = cls.__apply_env_overrides(config)
        return config

    def save(self, path: str) -> None:
        data = self.to_dict()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump(exclude_none=True)
        # Redact every secret-shaped field so config.save() never
        # writes payment provider keys, webhook secrets, credit-
        # bureau API keys, or the runtime identity private key to
        # disk. The original ``secrets.token`` removal and the
        # identity-private-key stripping remain for backwards
        # compatibility; the explicit field list below covers
        # every documented secret.
        secret_fields: tuple[str, ...] = (
            "key_secret",
            "webhook_secret",
            "api_token",
            "api_base_url",
            "token",
            "private_key",
            "encryption_passphrase",
            "cibil_api_key",
            "experian_api_key",
            "equifax_api_key",
            "ckyc_api_key",
            "pan_client_id",
            "pan_client_secret",
            "aadhaar_kua_id",
            "aadhaar_kua_license_key",
            "cibil_partner_id",
            "cibil_partner_key",
            "ckyc_search_provider_id",
            "ckyc_search_provider_key",
        )
        for section in d.values():
            if isinstance(section, dict):
                for f in secret_fields:
                    section.pop(f, None)
        if "secrets" in d and isinstance(d["secrets"], dict):
            d["secrets"].pop("token", None)
            if not d["secrets"]:
                d.pop("secrets")
        return d

    def enabled_services(self) -> list[str]:
        return [name for name, svc in self.services.items() if svc.enabled]

    @classmethod
    def __merge(cls, config: Configuration, data: dict[str, Any]) -> Configuration:
        """Overlay *data* on a deep copy of *config* and return a new
        ``Configuration``.

        Each top-level section is rebuilt with Pydantic's
        ``model_construct`` on the section's ``model_dump()`` dict
        merged with the corresponding input dict. Unknown fields
        raise ``ConfigurationError``; validation errors are
        re-raised as ``ConfigurationError`` with a section-prefixed
        message.
        """
        import copy

        from pydantic import ValidationError

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
            "kfs",
            "npa",
            "dpdpa",
            "razorpay",
            "credit_bureau",
            "underwriting",
            "kyc_providers",
        }
        unknown = set(data.keys()) - known_keys
        if unknown:
            raise ConfigurationError(f"unknown config keys: {', '.join(sorted(unknown))}")

        def overlay_section(
            model_cls: type[ModelT],
            section_name: str,
            current: ModelT,
            new_data: dict[str, Any],
        ) -> ModelT:
            unknown_fields = set(new_data) - set(model_cls.model_fields)
            if unknown_fields:
                raise ConfigurationError(f"{section_name}: unknown field(s): {', '.join(sorted(unknown_fields))}")
            merged: dict[str, Any] = {**current.model_dump(), **new_data}
            try:
                return model_cls.model_validate(merged)
            except ValidationError as exc:
                msg = "; ".join(
                    f"{section_name}.{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
                )
                raise ConfigurationError(msg) from exc

        section_overlays: dict[str, tuple[type[BaseModel], str]] = {
            "bus": (BusConfig, "bus"),
            "store": (StoreConfig, "store"),
            "logging": (LoggingConfig, "logging"),
            "identity": (IdentityConfig, "identity"),
            "authz": (AuthzConfig, "authz"),
            "metrics": (MetricsConfig, "metrics"),
            "migration": (MigrationConfig, "migration"),
            "tracing": (TracingConfig, "tracing"),
            "saga": (SagaConfig, "saga"),
            "secrets": (SecretsConfig, "secrets"),
            "recovery": (RecoveryConfig, "recovery"),
            "audit": (AuditConfig, "audit"),
        }
        for section_name, (model_cls, attr) in section_overlays.items():
            if section_name in data:
                new_section = dict(data[section_name])
                # Backwards-compat alias: ``logging.format`` in JSON
                # vs the field name ``log_format``.
                if attr == "logging" and "format" in new_section and "log_format" not in new_section:
                    new_section["log_format"] = new_section.pop("format")
                setattr(
                    config,
                    attr,
                    overlay_section(model_cls, section_name, getattr(config, attr), new_section),
                )

        if "fee" in data:
            fee_data = dict(data["fee"])
            schedules = fee_data.pop("schedules", None)
            if schedules is not None and isinstance(schedules, dict):
                config.fee.schedules.update(schedules)
            # Apply remaining fee fields via the standard overlay
            # path so a future fee.* field is supported automatically.
            config.fee = overlay_section(FeeConfig, "fee", config.fee, fee_data)

        if "governance" in data:
            gov_data = dict(data["governance"])
            ranges = gov_data.pop("param_ranges", None)
            if ranges is not None and isinstance(ranges, dict):
                for k, v in ranges.items():
                    if isinstance(v, (list, tuple)) and len(v) == 2:
                        config.governance.param_ranges[k] = [float(v[0]), float(v[1])]
            defaults = gov_data.pop("param_defaults", None)
            if defaults is not None and isinstance(defaults, dict):
                config.governance.param_defaults.update(defaults)
            config.governance = overlay_section(GovernanceConfig, "governance", config.governance, gov_data)

        # kfs, npa, dpdpa, razorpay, credit_bureau, underwriting,
        # kyc_providers all have a one-to-one Pydantic mapping;
        # overlay each via the standard path.
        overlay_map: dict[str, tuple[type[BaseModel], str]] = {
            "kfs": (KfsConfig, "kfs"),
            "npa": (NpaConfig, "npa"),
            "dpdpa": (DpdpaConfig, "dpdpa"),
            "razorpay": (RazorpayConfig, "razorpay"),
            "credit_bureau": (CreditBureauConfig, "credit_bureau"),
            "underwriting": (UnderwritingConfig, "underwriting"),
            "kyc_providers": (KycProviderConfig, "kyc_providers"),
        }
        for section_name, (model_cls, attr) in overlay_map.items():
            if section_name in data:
                setattr(
                    config,
                    attr,
                    overlay_section(model_cls, section_name, getattr(config, attr), data[section_name]),
                )

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
            if typ is bool:
                if val.lower() not in ("1", "true", "yes", "0", "false", "no", "on", "off"):
                    logger.warning("could not parse %s=%r as bool, leaving default in place", env_var, val)
                    continue
                coerced = val.lower() in ("1", "true", "yes", "on")
            else:
                try:
                    coerced = typ(val)
                except (ValueError, TypeError):
                    logger.warning(
                        "could not parse %s=%r as %s, leaving default in place",
                        env_var,
                        val,
                        typ.__name__,
                    )
                    continue
            if field_attr is None:
                setattr(config, section_attr, coerced)
            else:
                section = getattr(config, section_attr)
                setattr(section, field_attr, coerced)
        return config


def _build_service_names() -> list[str]:
    """Build the canonical service name list from the registry.

    The registry is the single source of truth — config used to
    duplicate the list which drifted out of sync. This helper
    produces the same ordering as the registry.
    """
    from underwrite.__service_registry__ import SERVICE_CLASSES

    return list(SERVICE_CLASSES.keys())


SERVICE_NAMES: list[str] = _build_service_names()
