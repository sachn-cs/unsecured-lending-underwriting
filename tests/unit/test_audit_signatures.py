"""Unit tests for audit event HMAC-SHA256 signatures."""

from __future__ import annotations

from ulu.compliance.audit_signatures import AuditSignatureService, SignedAuditEvent


class TestAuditSignatureService:
    def test_sign_and_verify(self) -> None:
        svc = AuditSignatureService(secret_key="test-key")
        signed = svc.sign("E1", "origination", {"amount": 1000})
        assert isinstance(signed, SignedAuditEvent)
        assert signed.event_id == "E1"
        assert svc.verify(signed, {"amount": 1000})

    def test_verify_tampered_payload_fails(self) -> None:
        svc = AuditSignatureService(secret_key="test-key")
        signed = svc.sign("E1", "origination", {"amount": 1000})
        assert svc.verify(signed, {"amount": 1000})
        assert not svc.verify(signed, {"amount": 2000})

    def test_verify_wrong_secret_fails(self) -> None:
        svc = AuditSignatureService(secret_key="test-key")
        signed = svc.sign("E1", "origination", {"amount": 1000})
        other = AuditSignatureService(secret_key="other-key")
        assert not other.verify(signed, {"amount": 1000})

    def test_verify_tampered_hash_fails(self) -> None:
        svc = AuditSignatureService(secret_key="test-key")
        signed = svc.sign("E1", "origination", {"amount": 1000})
        signed.payload_hash = "tampered"
        assert not svc.verify(signed, {"amount": 1000})
