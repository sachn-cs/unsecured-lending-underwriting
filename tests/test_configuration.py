"""Tests for Configuration — loading, unknown-key rejection, defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from underwrite.config import (
    AuthzConfig,
    BusConfig,
    Configuration,
    MetricsConfig,
    MigrationConfig,
    SagaConfig,
    StoreConfig,
    TracingConfig,
)
from underwrite.exceptions import ConfigurationError


class TestConfiguration:
    def test_default_has_all_services(self) -> None:
        config = Configuration.default()
        assert len(config.services) >= 18

    def test_rejects_unknown_top_level_key(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"unknown_key": 1}))
        with pytest.raises(ConfigurationError):
            Configuration.load(str(p))

    def test_merge_known_keys_ok(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"data_dir": "/tmp/test"}))
        config = Configuration.load(str(p))
        assert config.data_dir == "/tmp/test"

    def test_default_new_subsystems(self) -> None:
        config = Configuration.default()
        assert isinstance(config.authz, AuthzConfig)
        assert isinstance(config.bus, BusConfig)
        assert isinstance(config.metrics, MetricsConfig)
        assert isinstance(config.migration, MigrationConfig)
        assert isinstance(config.store, StoreConfig)
        assert isinstance(config.tracing, TracingConfig)
        assert isinstance(config.saga, SagaConfig)

    def test_merge_new_subsystem_fields(self, tmp_path: Path) -> None:
        data = {
            "authz": {"enabled": True, "policy_file": "/tmp/policy.json"},
            "bus": {"rate_limit": 50.0, "max_workers": 4},
            "metrics": {"enabled": False},
            "migration": {"auto_migrate": False},
            "store": {
                "backend": "postgres",
                "dsn": "host=localhost",
                "pool_size": 10,
                "read_backend": "filesystem",
                "read_dsn": "/tmp/read",
            },
            "tracing": {"enabled": True, "exporter": "console"},
            "saga": {"enabled": False},
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(data))
        config = Configuration.load(str(p))
        assert config.authz.enabled is True
        assert config.authz.policy_file == "/tmp/policy.json"
        assert config.bus.rate_limit == 50.0
        assert config.bus.max_workers == 4
        assert config.metrics.enabled is False
        assert config.migration.auto_migrate is False
        assert config.store.backend == "postgres"
        assert config.store.dsn == "host=localhost"
        assert config.store.pool_size == 10
        assert config.store.read_backend == "filesystem"
        assert config.store.read_dsn == "/tmp/read"
        assert config.tracing.enabled is True
        assert config.tracing.exporter == "console"
        assert config.saga.enabled is False

    def test_to_dict_includes_new_fields(self) -> None:
        config = Configuration.default()
        d = config.to_dict()
        assert "max_workers" in d["bus"]
        assert d["bus"]["max_workers"] == 0
        assert "pool_size" in d["store"]
        assert "read_backend" in d["store"]
        assert "key_ttl" in d["identity"]
        assert "key_grace" in d["identity"]
        assert "tracing" in d
        assert "saga" in d
        assert d["tracing"]["enabled"] is False
        assert d["saga"]["enabled"] is True

    def test_merge_identity_key_settings(self, tmp_path: Path) -> None:
        data = {
            "identity": {
                "key_ttl": 43200.0,
                "key_grace": 1800.0,
            },
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(data))
        config = Configuration.load(str(p))
        assert config.identity.key_ttl == 43200.0
        assert config.identity.key_grace == 1800.0

    def test_schema_rejects_invalid_backend(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"store": {"backend": "invalid_backend"}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "invalid_backend" in str(exc.value)

    def test_schema_rejects_invalid_tracing_exporter(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"tracing": {"exporter": "invalid_exporter"}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "invalid_exporter" in str(exc.value)

    def test_schema_rejects_invalid_logging_level(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"logging": {"level": "INVALID_LEVEL"}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "INVALID_LEVEL" in str(exc.value)

    def test_schema_rejects_invalid_logging_format(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"logging": {"format": "invalid_format"}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "invalid_format" in str(exc.value)

    def test_schema_rejects_invalid_logging_output(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"logging": {"output": "invalid_output"}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "invalid_output" in str(exc.value)

    def test_schema_accepts_stderr_logging_output(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"logging": {"output": "stderr"}}))
        config = Configuration.load(str(p))
        assert config.logging.output == "stderr"

    def test_schema_rejects_unknown_field(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"bus": {"unknown_field": 1}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "unknown_field" in str(exc.value)

    def test_schema_rejects_invalid_data_type(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"bus": {"rate_limit": "not_a_number"}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "rate_limit" in str(exc.value)

    def test_schema_rejects_negative_export_interval(self, tmp_path: Path) -> None:
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"metrics": {"export_interval": -1}}))
        with pytest.raises(ConfigurationError) as exc:
            Configuration.load(str(p))
        assert "export_interval" in str(exc.value)

    def test_valid_config_passes_schema(self, tmp_path: Path) -> None:
        valid = {
            "bus": {"backend": "local", "rate_limit": 100, "max_workers": 4},
            "store": {"backend": "filesystem"},
            "logging": {"level": "INFO", "format": "text"},
            "metrics": {"enabled": True, "export_interval": 60},
            "tracing": {"enabled": False, "exporter": "console"},
            "saga": {"enabled": True},
            "data_dir": "./data",
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(valid))
        config = Configuration.load(str(p))
        assert config.bus.backend == "local"
        assert config.bus.rate_limit == 100

    def test_to_dict_excludes_token(self) -> None:
        config = Configuration.default()
        config.secrets.token = "s3kr1t"
        d = config.to_dict()
        assert "secrets" in d
        assert "token" not in d["secrets"]

    def test_to_dict_includes_other_secret_fields(self) -> None:
        config = Configuration.default()
        config.secrets.backend = "vault"
        config.secrets.url = "https://vault.example.com"
        config.secrets.region = "us-east-1"
        d = config.to_dict()
        assert d["secrets"]["backend"] == "vault"
        assert d["secrets"]["url"] == "https://vault.example.com"
        assert d["secrets"]["region"] == "us-east-1"

    def test_env_override_coerces_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNDERWRITE_BUS_MAX_WORKERS", "8")
        config = Configuration.load()
        assert isinstance(config.bus.max_workers, int)
        assert config.bus.max_workers == 8

    def test_env_override_coerces_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNDERWRITE_BUS_RATE_LIMIT", "150.5")
        config = Configuration.load()
        assert isinstance(config.bus.rate_limit, float)
        assert config.bus.rate_limit == 150.5

    def test_env_override_coerces_bool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNDERWRITE_AUTHZ_ENABLED", "true")
        config = Configuration.load()
        assert config.authz.enabled is True

    def test_env_override_bool_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNDERWRITE_AUTHZ_ENABLED", "false")
        config = Configuration.load()
        assert config.authz.enabled is False
