"""Tests for secrets backends — EnvSecretsBackend, VaultSecretsBackend,
AwsSecretsBackend, and SecretsManager factory."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from underwrite.__secrets__ import (
    AwsSecretsBackend,
    EnvSecretsBackend,
    SecretsBackend,
    SecretsManager,
    VaultSecretsBackend,
)
from underwrite.__metrics__ import MetricsCollector


class TestEnvSecretsBackend:
    """Tests for EnvSecretsBackend — reads from UNDERWRITE_SECRET_<NAME>."""

    def test_get_returns_env_var_value(self) -> None:
        key = "DATABASE_URL"
        expected = "postgres://localhost:5432/db"
        with patch.dict(os.environ,
                        {"UNDERWRITE_SECRET_DATABASE_URL": expected},
                        clear=False):
            backend = EnvSecretsBackend()
            result = backend.get(key)
        assert result == expected

    def test_get_returns_none_for_missing_key(self) -> None:
        backend = EnvSecretsBackend()
        result = backend.get("NONEXISTENT")
        assert result is None

    def test_get_with_overridden_prefix(self) -> None:
        key = "API_KEY"
        expected = "sk-abc123"
        with patch.dict(os.environ, {"CUSTOM_SECRET_API_KEY": expected},
                        clear=False):
            backend = EnvSecretsBackend(prefix="CUSTOM_SECRET_")
            result = backend.get(key)
        assert result == expected

    def test_get_normalizes_key_path_separators(self) -> None:
        key = "vault/path/key"
        expected = "my-value"
        with patch.dict(os.environ,
                        {"UNDERWRITE_SECRET_VAULT_PATH_KEY": expected},
                        clear=False):
            backend = EnvSecretsBackend()
            result = backend.get(key)
        assert result == expected

    def test_get_normalizes_key_hyphens(self) -> None:
        key = "my-secret-key"
        expected = "my-value"
        with patch.dict(os.environ,
                        {"UNDERWRITE_SECRET_MY_SECRET_KEY": expected},
                        clear=False):
            backend = EnvSecretsBackend()
            result = backend.get(key)
        assert result == expected

    def test_set_is_noop(self) -> None:
        backend = EnvSecretsBackend()
        env_before = dict(os.environ)
        backend.set("SOME_KEY", "some-value")
        assert dict(os.environ) == env_before


def _make_hvac_mock() -> Mock:
    """Create a mock hvac module with proper package structure for sub-imports."""
    mock_hvac = Mock()
    mock_hvac.__path__ = []  # Make it look like a package
    return mock_hvac


def _make_hvac_module() -> dict[str, Mock]:
    """Create a full hvac module mock hierarchy including hvac.exceptions."""
    mock_hvac = Mock()
    mock_hvac.__path__ = []
    mock_hvac.Client = Mock()

    # Create hvac.exceptions sub-module
    class MockVaultError(Exception):
        pass

    mock_hvac_exceptions = Mock()
    mock_hvac_exceptions.VaultError = MockVaultError
    mock_hvac.exceptions = mock_hvac_exceptions

    return {"hvac": mock_hvac, "hvac.exceptions": mock_hvac_exceptions}


class TestVaultSecretsBackend:
    """Tests for VaultSecretsBackend — HashiCorp Vault KV v2."""

    def test_get_calls_hvac_and_returns_value(self) -> None:
        modules = _make_hvac_module()
        mock_hvac = modules["hvac"]
        mock_client = Mock()
        mock_hvac.Client.return_value = mock_client
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "value": "my-secret-value"
                }
            }
        }
        with patch.dict("sys.modules", modules):
            backend = VaultSecretsBackend(url="http://vault:8200",
                                          token="test-token")
            result = backend.get("my-key")
        assert result == "my-secret-value"
        mock_hvac.Client.assert_called_once_with(url="http://vault:8200",
                                                 token="test-token")
        mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="my-key", mount_point="secret")

    def test_get_raises_on_hvac_error(self) -> None:
        modules = _make_hvac_module()
        mock_hvac = modules["hvac"]
        mock_client = Mock()
        vault_error = modules["hvac"].exceptions.VaultError(
            "hvac connection failed")
        mock_client.secrets.kv.v2.read_secret_version.side_effect = vault_error
        with patch.dict("sys.modules", modules):
            backend = VaultSecretsBackend()
            mock_hvac.Client.return_value = mock_client
            with pytest.raises(type(vault_error)):
                backend.get("my-key")

    def test_get_uses_default_mount_point(self) -> None:
        modules = _make_hvac_module()
        mock_hvac = modules["hvac"]
        mock_client = Mock()
        mock_hvac.Client.return_value = mock_client
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "value": "val"
                }
            }
        }
        with patch.dict("sys.modules", modules):
            backend = VaultSecretsBackend()
            backend.get("k")
        mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="k", mount_point="secret")

    def test_get_uses_custom_mount_point(self) -> None:
        modules = _make_hvac_module()
        mock_hvac = modules["hvac"]
        mock_client = Mock()
        mock_hvac.Client.return_value = mock_client
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "value": "val"
                }
            }
        }
        with patch.dict("sys.modules", modules):
            backend = VaultSecretsBackend(mount_point="team-secrets")
            backend.get("k")
        mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="k", mount_point="team-secrets")

    def test_get_falls_back_to_vault_token_env(self) -> None:
        modules = _make_hvac_module()
        mock_hvac = modules["hvac"]
        mock_client = Mock()
        mock_hvac.Client.return_value = mock_client
        mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "value": "val"
                }
            }
        }
        with patch.dict("sys.modules", modules):
            with patch.dict(os.environ, {"VAULT_TOKEN": "env-token"},
                            clear=False):
                backend = VaultSecretsBackend()
                backend.get("k")
        mock_hvac.Client.assert_called_once_with(url="http://localhost:8200",
                                                 token="env-token")

    def test_set_calls_hvac(self) -> None:
        modules = _make_hvac_module()
        mock_hvac = modules["hvac"]
        mock_client = Mock()
        mock_hvac.Client.return_value = mock_client
        with patch.dict("sys.modules", modules):
            backend = VaultSecretsBackend(token="tok")
            backend.set("my-key", "my-value")
        mock_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="my-key", secret={"value": "my-value"}, mount_point="secret")

    def test_raises_on_missing_hvac_package(self) -> None:
        backend = VaultSecretsBackend()
        with patch.dict("sys.modules", {"hvac": None, "hvac.exceptions": None}):
            with patch("builtins.__import__") as mock_import:
                mock_import.side_effect = ImportError("no hvac")
                with pytest.raises(ImportError,
                                   match="VaultSecretsBackend requires hvac"):
                    backend.get("k")


class TestAwsSecretsBackend:
    """Tests for AwsSecretsBackend — AWS Secrets Manager."""

    def test_get_calls_boto3_and_returns_secret_string(self) -> None:
        mock_boto3 = Mock()
        mock_client = Mock()
        mock_boto3.client.return_value = mock_client
        mock_client.get_secret_value.return_value = {"SecretString": "my-val"}
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend(region="us-west-2")
            result = backend.get("my-key")
        assert result == "my-val"
        mock_boto3.client.assert_called_once_with("secretsmanager",
                                                  region_name="us-west-2")
        mock_client.get_secret_value.assert_called_once_with(SecretId="my-key")

    def test_get_returns_none_for_resource_not_found(self) -> None:
        mock_boto3 = Mock()
        mock_client = Mock()

        class FakeResourceNotFound(Exception):
            pass

        mock_client.exceptions.ResourceNotFoundException = FakeResourceNotFound
        mock_client.get_secret_value.side_effect = FakeResourceNotFound(
            "missing")
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend()
            result = backend.get("missing-key")
        assert result is None

    def test_raises_on_non_boto3_exception(self) -> None:
        mock_boto3 = Mock()
        mock_client = Mock()

        class FakeResourceNotFound(Exception):
            pass

        class FakeClientError(Exception):
            pass

        mock_client.exceptions.ResourceNotFoundException = FakeResourceNotFound
        mock_client.exceptions.ClientError = FakeClientError
        mock_client.get_secret_value.side_effect = RuntimeError(
            "connection error")
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend()
            with pytest.raises(RuntimeError, match="connection error"):
                backend.get("my-key")

    def test_set_calls_put_secret_value(self) -> None:
        mock_boto3 = Mock()
        mock_client = Mock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend(region="eu-west-1")
            backend.set("my-key", "my-val")
        mock_client.put_secret_value.assert_called_once_with(
            SecretId="my-key", SecretString="my-val")

    def test_set_calls_create_secret_on_resource_not_found(self) -> None:
        mock_boto3 = Mock()
        mock_client = Mock()

        class FakeResourceNotFound(Exception):
            pass

        mock_client.exceptions.ResourceNotFoundException = FakeResourceNotFound
        mock_client.put_secret_value.side_effect = FakeResourceNotFound(
            "missing")
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend()
            backend.set("new-key", "new-val")
        mock_client.create_secret.assert_called_once_with(
            Name="new-key", SecretString="new-val")
        assert mock_client.put_secret_value.call_count == 1

    def test_get_uses_default_region(self) -> None:
        mock_boto3 = Mock()
        mock_client = Mock()
        mock_boto3.client.return_value = mock_client
        mock_client.get_secret_value.return_value = {"SecretString": "v"}
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend()
            backend.get("k")
        mock_boto3.client.assert_called_once_with("secretsmanager",
                                                  region_name="us-east-1")

    def test_get_propagates_client_import_error(self) -> None:
        backend = AwsSecretsBackend()
        with patch.object(backend, "_client") as mock_client_method:
            mock_client_method.side_effect = ImportError("no boto3")
            with pytest.raises(ImportError, match="no boto3"):
                backend.get("k")

    def test_client_error_increments_metric(self) -> None:
        metrics = MetricsCollector()

        class FakeClientError(Exception):
            pass

        class FakeResourceNotFound(Exception):
            pass

        mock_boto3 = Mock()
        mock_client = Mock()
        mock_client.exceptions.ClientError = FakeClientError
        mock_client.exceptions.ResourceNotFoundException = FakeResourceNotFound
        mock_client.get_secret_value.side_effect = FakeClientError(
            {"Error": {
                "Code": "AccessDeniedException"
            }}, "get_secret_value")
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = AwsSecretsBackend(metrics_collector=metrics)
            with pytest.raises(FakeClientError):
                backend.get("my-key")
        snapshot = metrics.snapshot()
        assert any(
            k.startswith("secrets.failures") for k in snapshot["counters"])


class TestSecretsManager:
    """Tests for SecretsManager — factory and delegating methods."""

    def test_load_private_key_delegates_to_backend(self) -> None:
        mock_backend = Mock(spec=SecretsBackend)
        mock_backend.get.return_value = "pem-data"
        mgr = SecretsManager(backend=mock_backend)
        result = mgr.load_private_key("my-service")
        assert result == "pem-data"
        mock_backend.get.assert_called_once_with(
            "underwrite/my-service/private_key")

    def test_store_private_key_delegates_to_backend(self) -> None:
        mock_backend = Mock(spec=SecretsBackend)
        mgr = SecretsManager(backend=mock_backend)
        mgr.store_private_key("my-service", "pem-data")
        mock_backend.set.assert_called_once_with(
            "underwrite/my-service/private_key", "pem-data")

    def test_build_backend_none_config_returns_env(self) -> None:
        mgr = SecretsManager(config=None)
        assert isinstance(mgr._SecretsManager__backend, EnvSecretsBackend)

    def test_build_backend_vault_config(self) -> None:
        cfg = SimpleNamespace(backend="vault",
                              url="http://vault:8200",
                              token="tok")
        mgr = SecretsManager(config=cfg)
        backend = mgr._SecretsManager__backend
        assert isinstance(backend, VaultSecretsBackend)

    def test_build_backend_aws_config(self) -> None:
        cfg = SimpleNamespace(backend="aws", region="eu-central-1")
        mgr = SecretsManager(config=cfg)
        backend = mgr._SecretsManager__backend
        assert isinstance(backend, AwsSecretsBackend)

    def test_build_backend_unknown_backend_falls_back_to_env(self) -> None:
        cfg = SimpleNamespace(backend="unknown")
        mgr = SecretsManager(config=cfg)
        backend = mgr._SecretsManager__backend
        assert isinstance(backend, EnvSecretsBackend)

    def test_backend_provided_directly_is_used(self) -> None:
        mock_backend = Mock(spec=SecretsBackend)
        mgr = SecretsManager(backend=mock_backend,
                             config=SimpleNamespace(backend="vault"))
        assert mgr._SecretsManager__backend is mock_backend
