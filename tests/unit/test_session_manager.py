"""Unit tests for session management."""

from __future__ import annotations

import pytest

from ulu.api.session_manager import SessionManager
from ulu.errors import ProtocolError


class TestSessionManager:
    def test_login_issues_tokens(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        pair = mgr.login("u1", "borrower")
        assert pair.access_token
        assert pair.refresh_token
        assert pair.token_type == "bearer"

    def test_validate_access_token(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        pair = mgr.login("u1", "borrower")
        payload = mgr.validate_access_token(pair.access_token)
        assert payload["sub"] == "u1"
        assert payload["role"] == "borrower"
        assert payload["type"] == "access"

    def test_validate_expired_token(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        mgr._access_ttl = -1
        pair = mgr.login("u1", "borrower")
        with pytest.raises(ProtocolError, match="token expired"):
            mgr.validate_access_token(pair.access_token)

    def test_validate_revoked_token(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        pair = mgr.login("u1", "borrower")
        mgr.revoke(pair.access_token)
        with pytest.raises(ProtocolError, match="revoked"):
            mgr.validate_access_token(pair.access_token)

    def test_refresh_token(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        pair = mgr.login("u1", "borrower")
        new_pair = mgr.refresh(pair.refresh_token)
        assert new_pair.access_token
        assert new_pair.access_token != pair.access_token

    def test_refresh_invalid_token(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        with pytest.raises(ProtocolError, match="invalid refresh token"):
            mgr.refresh("not-a-token")

    def test_refresh_reused_after_revoke(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        pair = mgr.login("u1", "borrower")
        mgr.revoke(pair.refresh_token)
        with pytest.raises(ProtocolError, match="refresh token not recognized"):
            mgr.refresh(pair.refresh_token)

    def test_is_revoked(self) -> None:
        mgr = SessionManager()
        mgr.clear_stores()
        pair = mgr.login("u1", "borrower")
        import jwt

        payload = jwt.decode(pair.access_token, options={"verify_signature": False})
        jti = payload["jti"]
        assert mgr.is_revoked(jti) is False
        mgr.revoke(pair.access_token)
        assert mgr.is_revoked(jti) is True
