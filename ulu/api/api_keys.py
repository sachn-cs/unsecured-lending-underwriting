"""API key management for service-to-service authentication."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, Header, HTTPException

API_KEY_PREFIX = "ulu_"


@dataclass
class ApiKey:
    """Represents an API key record."""

    key_id: str
    hashed_secret: str
    scopes: list[str] = field(default_factory=list)
    expires_at: float = 0.0
    revoked: bool = False


class ApiKeyService:
    """In-memory API key store (production: backed by PostgreSQL with hashed secrets)."""

    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}

    def _hash(self, secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    def generate_key(self, scopes: list[str] | None = None, expires_at: float = 0.0) -> tuple[str, str]:
        """Returns (key_id, plain_secret) and stores hashed version."""
        key_id = secrets.token_urlsafe(16)
        plain_secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
        hashed = self._hash(plain_secret)
        self._keys[key_id] = ApiKey(
            key_id=key_id,
            hashed_secret=hashed,
            scopes=scopes or [],
            expires_at=expires_at,
        )
        return key_id, plain_secret

    def validate_key(self, plain_secret: str) -> ApiKey:
        """Validates a plain secret against stored hashes."""
        # Extract key_id from the prefix if present; for this in-memory store we brute-force
        hashed = self._hash(plain_secret)
        for key in self._keys.values():
            if key.hashed_secret == hashed and not key.revoked:
                import time

                if key.expires_at > 0 and time.time() > key.expires_at:
                    raise HTTPException(status_code=401, detail="api key expired")
                return key
        raise HTTPException(status_code=401, detail="invalid api key")

    def revoke_key(self, key_id: str) -> bool:
        """Revokes an API key by key_id."""
        if key_id not in self._keys:
            return False
        self._keys[key_id].revoked = True
        return True

    def list_keys(self) -> list[dict[str, Any]]:
        """Returns non-sensitive metadata for all keys."""
        return [
            {
                "key_id": k.key_id,
                "scopes": k.scopes,
                "expires_at": k.expires_at,
                "revoked": k.revoked,
            }
            for k in self._keys.values()
        ]


_api_key_service = ApiKeyService()


def get_api_key_service() -> ApiKeyService:
    return _api_key_service


async def require_api_key(
    authorization: str | None = Header(default=None, alias="Authorization"),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKey:
    """Dependency that validates API key bearer token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization header")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="invalid authorization format")
    return service.validate_key(parts[1])
