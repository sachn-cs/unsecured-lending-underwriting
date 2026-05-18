"""Unit tests for API key management."""

from __future__ import annotations

import time

import pytest

from ulu.api.api_keys import ApiKeyService, require_api_key


class TestApiKeyService:
    def test_generate_and_validate(self) -> None:
        svc = ApiKeyService()
        key_id, secret = svc.generate_key(scopes=["read", "write"])
        assert key_id
        assert secret.startswith("ulu_")
        key = svc.validate_key(secret)
        assert key.key_id == key_id
        assert key.scopes == ["read", "write"]

    def test_validate_invalid_key(self) -> None:
        svc = ApiKeyService()
        with pytest.raises(Exception, match="invalid api key"):
            svc.validate_key("ulu_invalid")

    def test_revoke_key(self) -> None:
        svc = ApiKeyService()
        key_id, secret = svc.generate_key()
        assert svc.revoke_key(key_id) is True
        with pytest.raises(Exception, match="invalid api key"):
            svc.validate_key(secret)

    def test_revoke_unknown_key(self) -> None:
        svc = ApiKeyService()
        assert svc.revoke_key("unknown") is False

    def test_expired_key_rejected(self) -> None:
        svc = ApiKeyService()
        key_id, secret = svc.generate_key(expires_at=time.time() - 1)
        with pytest.raises(Exception, match="expired"):
            svc.validate_key(secret)

    def test_list_keys_omits_secret(self) -> None:
        svc = ApiKeyService()
        svc.generate_key(scopes=["read"])
        keys = svc.list_keys()
        assert len(keys) == 1
        assert "hashed_secret" not in keys[0]

    def test_require_api_key_dependency_missing_header(self) -> None:
        with pytest.raises(Exception, match="missing authorization header"):
            import asyncio

            asyncio.run(require_api_key(None))

    def test_require_api_key_dependency_invalid_format(self) -> None:
        with pytest.raises(Exception, match="invalid authorization format"):
            import asyncio

            asyncio.run(require_api_key("Basic abc"))
