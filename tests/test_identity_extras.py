"""Tests for KeyRotationManager."""

from __future__ import annotations

import time

from underwrite.__identity__ import KeyRotationManager


class TestKeyRotationManager:

    def test_get_or_create_creates_new(self) -> None:
        mgr = KeyRotationManager()
        identity = mgr.get_or_create("svc1")
        assert identity.service_id == "svc1"

    def test_get_or_create_returns_cached(self) -> None:
        mgr = KeyRotationManager(ttl_seconds=3600)
        first = mgr.get_or_create("svc1")
        second = mgr.get_or_create("svc1")
        assert first.public_key == second.public_key

    def test_rotate_creates_new_key(self) -> None:
        mgr = KeyRotationManager()
        first = mgr.get_or_create("svc1")
        second = mgr.rotate("svc1")
        assert first.public_key != second.public_key

    def test_verify_with_rotation_current(self) -> None:
        mgr = KeyRotationManager()
        identity = mgr.get_or_create("svc1")
        sig = identity.sign("hello")
        ok = mgr.verify_with_rotation("hello", sig, "svc1", identity.public_key)
        assert ok is True

    def test_verify_with_rotation_previous_grace(self) -> None:
        mgr = KeyRotationManager(ttl_seconds=0.001, grace_period=3600)
        identity = mgr.get_or_create("svc1")
        sig = identity.sign("hello")
        time.sleep(0.005)
        mgr.rotate("svc1")
        ok = mgr.verify_with_rotation("hello", sig, "svc1", identity.public_key)
        assert ok is True

    def test_verify_with_rotation_expired_grace(self) -> None:
        mgr = KeyRotationManager(ttl_seconds=0.001, grace_period=0.001)
        identity = mgr.get_or_create("svc1")
        sig = identity.sign("hello")
        time.sleep(0.005)
        mgr.rotate("svc1")
        time.sleep(0.005)
        ok = mgr.verify_with_rotation("hello", sig, "svc1", identity.public_key)
        assert ok is False

    def test_verify_wrong_key_returns_false(self) -> None:
        mgr = KeyRotationManager()
        mgr.get_or_create("svc1")
        ok = mgr.verify_with_rotation("hello", "bad_sig", "svc1", "bad_key")
        assert ok is False
