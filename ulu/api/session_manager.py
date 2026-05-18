"""Session management with JWT access/refresh tokens and token blacklist.

Item 5 from production roadmap.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

from ulu.errors import ProtocolError
from ulu.infra.config import settings
from ulu.infra.logging import logger


@dataclass
class TokenPair:
    """Access and refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


class SessionManager:
    """Manages OAuth2-style token issuance, validation, and revocation.

    In production the refresh-token store and blacklist should be backed
    by Redis or PostgreSQL for cross-instance consistency.
    """

    def __init__(self) -> None:
        self._refresh_store: dict[str, dict[str, Any]] = {}
        self._blacklist: set[str] = set()
        self._access_ttl: int = settings.jwt_expiry_minutes * 60
        self._refresh_ttl: int = 7 * 24 * 60 * 60  # 7 days

    def _issue(self, payload: dict[str, Any], ttl: int) -> str:
        now = int(time.time())
        claims = {
            **payload,
            "iat": now,
            "exp": now + ttl,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def _issue_with_jti(self, payload: dict[str, Any], ttl: int) -> tuple[str, str]:
        """Returns (token, jti) pair."""
        jti = str(uuid.uuid4())
        now = int(time.time())
        claims = {
            **payload,
            "iat": now,
            "exp": now + ttl,
            "jti": jti,
        }
        return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm), jti

    def login(self, user_id: str, role: str) -> TokenPair:
        """Issues access and refresh tokens for a user."""
        access_payload = {"sub": user_id, "role": role, "type": "access"}
        refresh_payload = {"sub": user_id, "role": role, "type": "refresh"}
        access_token = self._issue(access_payload, self._access_ttl)
        refresh_token, refresh_jti = self._issue_with_jti(refresh_payload, self._refresh_ttl)

        self._refresh_store[refresh_jti] = {
            "user_id": user_id,
            "role": role,
            "issued_at": int(time.time()),
        }

        logger.info("session_login", user_id=user_id, role=role)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._access_ttl,
        )

    def validate_access_token(self, token: str) -> dict[str, Any]:
        """Validates an access token and returns its payload."""
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
        except jwt.ExpiredSignatureError as exc:
            raise ProtocolError("token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise ProtocolError("invalid token") from exc

        if payload.get("type") != "access":
            raise ProtocolError("token is not an access token")
        if payload.get("jti") in self._blacklist:
            raise ProtocolError("token has been revoked")
        return payload

    def refresh(self, refresh_token: str) -> TokenPair:
        """Issues a new access token using a valid refresh token."""
        try:
            payload = jwt.decode(
                refresh_token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
        except jwt.ExpiredSignatureError as exc:
            raise ProtocolError("refresh token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise ProtocolError("invalid refresh token") from exc

        if payload.get("type") != "refresh":
            raise ProtocolError("token is not a refresh token")

        jti = payload.get("jti")
        if jti not in self._refresh_store:
            raise ProtocolError("refresh token not recognized")

        stored = self._refresh_store[jti]
        return self.login(stored["user_id"], stored["role"])

    def revoke(self, token: str) -> None:
        """Adds a token to the blacklist (logout)."""
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
                options={"verify_exp": False},
            )
            jti = payload.get("jti")
            if jti:
                self._blacklist.add(jti)
                # Also clean up refresh store if it was a refresh token
                if payload.get("type") == "refresh" and jti in self._refresh_store:
                    del self._refresh_store[jti]
                logger.info("session_revoke", jti=jti)
        except jwt.InvalidTokenError:
            pass  # Ignore invalid tokens during revoke

    def is_revoked(self, jti: str) -> bool:
        """Returns True if the token JTI is in the blacklist."""
        return jti in self._blacklist

    def clear_stores(self) -> None:
        """Clears in-memory stores (useful in tests)."""
        self._refresh_store.clear()
        self._blacklist.clear()
