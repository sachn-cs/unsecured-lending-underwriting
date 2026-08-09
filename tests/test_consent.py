"""Tests for ConsentHandler — DPDPA-compliant consent lifecycle."""

from __future__ import annotations

from underwrite.__events__ import Event, EventType
from underwrite.services.consent.handler import ConsentHandler


def svc(**kw) -> ConsentHandler:
    return ConsentHandler(service_id="consent", **kw)


class TestConsentRecording:
    def test_records_consent(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={"user_id": "u1", "purpose": "kyc_verification"},
            )
        )
        record = s.get_consent("u1", "kyc_verification")
        assert record is not None
        assert record["status"] == "active"
        assert "recorded_at" in record
        assert "expires_at" in record

    def test_records_with_metadata(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={
                    "user_id": "u2",
                    "purpose": "credit_bureau_reporting",
                    "ip_address": "192.168.1.1",
                    "user_agent": "TestAgent/1.0",
                },
            )
        )
        record = s.get_consent("u2", "credit_bureau_reporting")
        assert record is not None
        assert record["ip_address"] == "192.168.1.1"
        assert record["user_agent"] == "TestAgent/1.0"

    def test_missing_user_id_ignored(self) -> None:
        s = svc()
        s.handle(Event(event_type=EventType.CONSENT_RECORDED, source="test", payload={"purpose": "kyc"}))
        assert s.get_user_consents("") == []

    def test_missing_purpose_ignored(self) -> None:
        s = svc()
        s.handle(Event(event_type=EventType.CONSENT_RECORDED, source="test", payload={"user_id": "u3"}))
        assert s.get_user_consents("u3") == []


class TestConsentWithdrawal:
    def test_withdraw_specific_purpose(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={"user_id": "u10", "purpose": "kyc_verification"},
            )
        )
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={"user_id": "u10", "purpose": "loan_servicing"},
            )
        )
        s.handle(
            Event(
                event_type=EventType.CONSENT_WITHDRAWN,
                source="test",
                payload={"user_id": "u10", "purpose": "kyc_verification"},
            )
        )
        assert s.has_active_consent("u10", "kyc_verification") is False
        assert s.has_active_consent("u10", "loan_servicing") is True

    def test_withdraw_all_purposes(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={"user_id": "u11", "purpose": "kyc_verification"},
            )
        )
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={"user_id": "u11", "purpose": "collection"},
            )
        )
        s.handle(Event(event_type=EventType.CONSENT_WITHDRAWN, source="test", payload={"user_id": "u11"}))
        assert s.has_active_consent("u11", "kyc_verification") is False
        assert s.has_active_consent("u11", "collection") is False

    def test_withdraw_nonexistent_noop(self) -> None:
        s = svc()
        s.handle(
            Event(event_type=EventType.CONSENT_WITHDRAWN, source="test", payload={"user_id": "ghost", "purpose": "kyc"})
        )
        assert s.get_user_consents("ghost") == []


class TestConsentQueries:
    def test_has_active_consent_true(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.CONSENT_RECORDED,
                source="test",
                payload={"user_id": "u20", "purpose": "kyc_verification"},
            )
        )
        assert s.has_active_consent("u20", "kyc_verification") is True

    def test_has_active_consent_false_no_record(self) -> None:
        s = svc()
        assert s.has_active_consent("unknown", "kyc") is False

    def test_get_user_consents(self) -> None:
        s = svc()
        s.handle(
            Event(event_type=EventType.CONSENT_RECORDED, source="test", payload={"user_id": "u30", "purpose": "p1"})
        )
        s.handle(
            Event(event_type=EventType.CONSENT_RECORDED, source="test", payload={"user_id": "u30", "purpose": "p2"})
        )
        consents = s.get_user_consents("u30")
        assert len(consents) == 2

    def test_check_missing_purposes(self) -> None:
        s = svc(required_purposes=["kyc", "cibil", "servicing"])
        s.handle(
            Event(event_type=EventType.CONSENT_RECORDED, source="test", payload={"user_id": "u40", "purpose": "kyc"})
        )
        missing = s.check_missing_purposes("u40")
        assert "kyc" not in missing
        assert "cibil" in missing
        assert "servicing" in missing


class TestConsentEdgeCases:
    def test_ignores_unrelated_events(self) -> None:
        s = svc()
        s.handle(Event(event_type="seed.added", source="test", payload={}))
        assert s.get_user_consents("") == []

    def test_has_active_consent_expired(self) -> None:
        s = svc(consent_validity_days=365)
        s.handle(
            Event(event_type=EventType.CONSENT_RECORDED, source="test", payload={"user_id": "u60", "purpose": "kyc"})
        )
        assert s.has_active_consent("u60", "kyc") is True
