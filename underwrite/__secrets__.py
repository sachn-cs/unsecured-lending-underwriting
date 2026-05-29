"""Secrets management — loads private keys from Vault, AWS SM, or env vars."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class SecretsBackend(ABC):
    """Abstract secrets backend."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Retrieves a secret value."""

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Stores a secret value."""


class EnvSecretsBackend(SecretsBackend):
    """Reads secrets from UNDERWRITE_SECRET_<NAME> env vars (read-only)."""

    def __init__(self, prefix: str = "UNDERWRITE_SECRET_") -> None:
        self.__prefix = prefix

    def get(self, key: str) -> str | None:
        env_key = f"{self.__prefix}{key.upper().replace('/', '_').replace('-', '_')}"
        return os.environ.get(env_key)

    def set(self, key: str, value: str) -> None:
        pass  # read-only


class VaultSecretsBackend(SecretsBackend):
    """HashiCorp Vault KV v2 backend."""

    def __init__(self,
                 url: str = "http://localhost:8200",
                 token: str | None = None,
                 mount_point: str = "secret",
                 metrics_collector: Any | None = None) -> None:
        self.__url = url
        self.__token = token or os.environ.get("VAULT_TOKEN", "")
        self.__mount_point = mount_point
        self.__metrics: Any | None = metrics_collector

    def get(self, key: str) -> str | None:
        try:
            import hvac
        except ImportError:
            raise ImportError(
                "VaultSecretsBackend requires hvac; pip install hvac") from None
        from hvac.exceptions import VaultError
        client = hvac.Client(url=self.__url, token=self.__token)
        try:
            resp = client.secrets.kv.v2.read_secret_version(
                path=key, mount_point=self.__mount_point)
            data = resp.get("data", {}).get("data", {})
            return data.get("value")
        except VaultError:
            logger.exception("vault read failed for %s", key)
            if self.__metrics:
                self.__metrics.increment("secrets.failures", {
                    "backend": "vault",
                    "key": key
                })
            raise

    def set(self, key: str, value: str) -> None:
        try:
            import hvac
        except ImportError:
            raise ImportError(
                "VaultSecretsBackend requires hvac; pip install hvac") from None
        client = hvac.Client(url=self.__url, token=self.__token)
        client.secrets.kv.v2.create_or_update_secret(
            path=key, secret={"value": value}, mount_point=self.__mount_point)


class AwsSecretsBackend(SecretsBackend):
    """AWS Secrets Manager backend."""

    def __init__(self,
                 region: str = "us-east-1",
                 metrics_collector: Any | None = None) -> None:
        self.__region = region
        self.__metrics: Any | None = metrics_collector

    def _client(self):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "AwsSecretsBackend requires boto3; pip install boto3") from None
        return boto3.client("secretsmanager", region_name=self.__region)

    def get(self, key: str) -> str | None:
        client = self._client()
        try:
            resp = client.get_secret_value(SecretId=key)
            return resp.get("SecretString")
        except client.exceptions.ResourceNotFoundException:
            return None
        except client.exceptions.ClientError:
            logger.exception("aws secrets read failed for %s", key)
            if self.__metrics:
                self.__metrics.increment("secrets.failures", {
                    "backend": "aws",
                    "key": key
                })
            raise

    def set(self, key: str, value: str) -> None:
        client = self._client()
        try:
            client.put_secret_value(SecretId=key, SecretString=value)
        except client.exceptions.ResourceNotFoundException:
            client.create_secret(Name=key, SecretString=value)


class SecretsManager:
    """Manages secret backends and loads private keys for Identity."""

    def __init__(self,
                 backend: SecretsBackend | None = None,
                 config: Any | None = None) -> None:
        self.__backend = backend or self.__build_backend(config)

    @staticmethod
    def __build_backend(config: Any) -> SecretsBackend:
        if config is None:
            return EnvSecretsBackend()
        if config.backend == "vault":
            return VaultSecretsBackend(
                url=config.url or "http://localhost:8200",
                token=getattr(config, "token", None),
            )
        if config.backend == "aws":
            return AwsSecretsBackend(
                region=getattr(config, "region", "us-east-1"))
        return EnvSecretsBackend()

    def load_private_key(self, service_id: str) -> str | None:
        """Loads a PEM-encoded private key for *service_id*."""
        return self.__backend.get(f"underwrite/{service_id}/private_key")

    def store_private_key(self, service_id: str, pem: str) -> None:
        """Stores a PEM-encoded private key for *service_id*."""
        self.__backend.set(f"underwrite/{service_id}/private_key", pem)


__all__ = [
    "SecretsBackend",
    "EnvSecretsBackend",
    "VaultSecretsBackend",
    "AwsSecretsBackend",
    "SecretsManager",
]
