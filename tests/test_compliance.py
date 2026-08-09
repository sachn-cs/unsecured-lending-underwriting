"""Tests for ComplianceHandler — RBI KYC/AML checks.

Tests verify behavior through emitted events:
  - KYC_VERIFIED for valid PAN + Aadhaar (with Verhoeff check)
  - KYC_REJECTED for invalid PAN or Aadhaar
  - AML_FROZEN/AML_CLEARED for blocklist/keyword matches
  - Risk scoring with keyword weights
  - CKYC verification event emission
  - Edge cases: empty fields, case sensitivity, missing payload
"""

from __future__ import annotations
from underwrite.__store__ import MemoryStore

import json
import os
import tempfile
from unittest.mock import patch

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.compliance.handler import (
    ComplianceHandler,
    pan_category,
    verify_aadhaar_checksum,
)


def compliance(bus=None) -> ComplianceHandler:
    svc = ComplianceHandler(service_id="compliance", bus=bus, store=MemoryStore())
    svc.repo.save({})
    return svc


class TestAadhaarChecksum:
    def test_valid_aadhaar_passes(self) -> None:
        assert verify_aadhaar_checksum("123456789012") is True

    def test_invalid_aadhaar_fails(self) -> None:
        assert verify_aadhaar_checksum("123456789011") is False

    def test_all_zeros_fails(self) -> None:
        assert verify_aadhaar_checksum("000000000000") is False

    def test_short_aadhaar_fails(self) -> None:
        assert verify_aadhaar_checksum("12345678") is False

    def test_long_aadhaar_fails(self) -> None:
        assert verify_aadhaar_checksum("1234567890123") is False

    def test_non_numeric_fails(self) -> None:
        assert verify_aadhaar_checksum("1234abcd9012") is False

    def test_empty_fails(self) -> None:
        assert verify_aadhaar_checksum("") is False


class TestPanCategory:
    def test_individual_pan(self) -> None:
        assert pan_category("ABCPE1234F") == "Individual"

    def test_company_pan(self) -> None:
        assert pan_category("ABCCA1234F") == "Company"

    def test_firm_pan(self) -> None:
        assert pan_category("ABCFE1234K") == "Firm"

    def test_unknown_category(self) -> None:
        assert pan_category("ABCXE1234K") == "Unknown"


class TestComplianceService:
    def __assert_kyc_result(self, payload: dict, *, expect_kyc: bool, expect_reason: str = "") -> list[Event]:
        bus = LocalBus()
        all_events: list[Event] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(Event(event_type=EventType.USER_ADDED, source="test", payload=payload))
        kyc_rejected = [e for e in all_events if e.event_type == EventType.KYC_REJECTED.value]
        kyc_verified = [e for e in all_events if e.event_type == EventType.KYC_VERIFIED.value]
        if expect_kyc:
            assert len(kyc_rejected) == 0, f"Expected no rejection but got: {kyc_rejected}"
            assert len(kyc_verified) == 1, f"Expected KYC_VERIFIED but got {len(kyc_verified)}"
        else:
            assert len(kyc_verified) == 0, f"Expected no KYC_VERIFIED but got: {kyc_verified}"
            assert len(kyc_rejected) == 1, f"Expected KYC_REJECTED but got {len(kyc_rejected)}"
            if expect_reason:
                assert (
                    kyc_rejected[0].payload["reason"] == expect_reason
                ), f"Expected reason '{expect_reason}' got '{kyc_rejected[0].payload.get('reason')}'"
        return all_events

    def test_verified_with_valid_pan_and_aadhaar(self) -> None:
        events = self.__assert_kyc_result(
            {"user": "alice", "pan": "ABCPE1234F", "aadhaar": "123456789012"},
            expect_kyc=True,
        )
        types = [e.event_type for e in events]
        assert EventType.CKYC_VERIFY.value in types
        assert "kyc.video_initiated" in types

    def test_rejected_with_invalid_pan(self) -> None:
        self.__assert_kyc_result(
            {"user": "carol", "pan": "INVALID", "aadhaar": "123456789012"},
            expect_kyc=False,
            expect_reason="invalid_pan_format",
        )

    def test_rejected_with_invalid_aadhaar_checksum(self) -> None:
        self.__assert_kyc_result(
            {"user": "dave", "pan": "ABCDE1234F", "aadhaar": "123456789011"},
            expect_kyc=False,
            expect_reason="invalid_aadhaar_checksum",
        )

    def test_rejected_missing_aadhaar_field(self) -> None:
        self.__assert_kyc_result(
            {"user": "eve", "pan": "ABCDE1234F"},
            expect_kyc=False,
            expect_reason="invalid_aadhaar_checksum",
        )

    def test_rejected_missing_pan_field(self) -> None:
        self.__assert_kyc_result(
            {"user": "frank", "aadhaar": "123456789012"},
            expect_kyc=False,
            expect_reason="invalid_pan_format",
        )

    def test_rejected_empty_pan(self) -> None:
        self.__assert_kyc_result(
            {"user": "grace", "pan": "", "aadhaar": "123456789012"},
            expect_kyc=False,
            expect_reason="invalid_pan_format",
        )

    def test_accepted_lowercase_pan_upper_normalized(self) -> None:
        self.__assert_kyc_result(
            {"user": "heidi", "pan": "abcpe1234f", "aadhaar": "123456789012"},
            expect_kyc=True,
        )

    def test_rejected_aadhaar_too_short(self) -> None:
        self.__assert_kyc_result(
            {"user": "jack", "pan": "ABCDE1234F", "aadhaar": "12345678"},
            expect_kyc=False,
            expect_reason="invalid_aadhaar_checksum",
        )

    def test_rejected_aadhaar_too_long(self) -> None:
        self.__assert_kyc_result(
            {"user": "karen", "pan": "ABCDE1234F", "aadhaar": "1234567890123"},
            expect_kyc=False,
            expect_reason="invalid_aadhaar_checksum",
        )

    def test_rejected_aadhaar_with_spaces(self) -> None:
        self.__assert_kyc_result(
            {"user": "leo", "pan": "ABCDE1234F", "aadhaar": "1234 5678 9012"},
            expect_kyc=False,
            expect_reason="invalid_aadhaar_checksum",
        )

    def test_rejected_aadhaar_all_zeros(self) -> None:
        self.__assert_kyc_result(
            {"user": "neo", "pan": "ABCDE1234F", "aadhaar": "000000000000"},
            expect_kyc=False,
            expect_reason="invalid_aadhaar_checksum",
        )

    def test_ignores_non_user_added_events(self) -> None:
        bus = LocalBus()
        all_events: list[Event] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={}))
        kyc_events = [
            e
            for e in all_events
            if e.event_type
            in (
                EventType.KYC_VERIFIED.value,
                EventType.KYC_REJECTED.value,
            )
        ]
        assert len(kyc_events) == 0

    def test_missing_user_field_does_not_crash(self) -> None:
        bus = LocalBus()
        verified: list[Event] = []
        bus.subscribe(EventType.KYC_VERIFIED, lambda e: verified.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={"pan": "ABCDE1234F", "aadhaar": "123456789012"},
            )
        )
        assert len(verified) == 1
        assert verified[0].payload["user"] == ""

    def test_aml_cleared_when_no_blocklist(self) -> None:
        bus = LocalBus()
        cleared: list[Event] = []
        bus.subscribe(EventType.AML_CLEARED, lambda e: cleared.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={
                    "user": "oscar",
                    "pan": "ABCDE1234F",
                    "aadhaar": "123456789012",
                    "name": "Oscar Wilde",
                },
            )
        )
        assert len(cleared) == 1

    def test_aml_frozen_on_blocklist_match(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(["oscar"], f)
            bl_path = f.name
        try:
            with patch.dict(os.environ, {"AML_BLOCKLIST_PATH": bl_path}, clear=False):
                bus = LocalBus()
                frozen: list[Event] = []
                bus.subscribe(EventType.AML_FROZEN, lambda e: frozen.append(e))
                svc = ComplianceHandler(service_id="compliance", bus=bus, aml_blocklist_path=bl_path, store=MemoryStore())
                bus.start()
                svc.handle(
                    Event(
                        event_type=EventType.USER_ADDED,
                        source="test",
                        payload={
                            "user": "oscar",
                            "pan": "ABCDE1234F",
                            "aadhaar": "123456789012",
                        },
                    )
                )
                assert len(frozen) == 1
                assert frozen[0].payload["aml_status"] == "frozen"
        finally:
            os.unlink(bl_path)

    def test_aml_frozen_on_keyword_match(self) -> None:
        bus = LocalBus()
        frozen: list[Event] = []
        bus.subscribe(EventType.AML_FROZEN, lambda e: frozen.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={
                    "user": "innocent",
                    "pan": "ABCDE1234F",
                    "aadhaar": "123456789012",
                    "name": "Known Terrorist",
                },
            )
        )
        assert len(frozen) == 1
        assert frozen[0].payload["aml_status"] == "frozen"

    def test_aml_flagged_on_medium_risk_keyword(self) -> None:
        bus = LocalBus()
        flagged: list[Event] = []
        bus.subscribe("aml.flagged", lambda e: flagged.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={
                    "user": "pep_adjacent",
                    "pan": "ABCDE1234F",
                    "aadhaar": "123456789012",
                    "name": "Local PEP Contact",
                },
            )
        )
        assert len(flagged) == 1

    def test_pan_category_in_kyc_verified(self) -> None:
        bus = LocalBus()
        verified: list[Event] = []
        bus.subscribe(EventType.KYC_VERIFIED, lambda e: verified.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={"user": "bob", "pan": "ABCPE1234F", "aadhaar": "123456789012"},
            )
        )
        assert len(verified) == 1
        assert verified[0].payload["pan_category"] == "Individual"

    def test_ckyc_verify_emitted_on_kyc_pass(self) -> None:
        bus = LocalBus()
        ckyc: list[Event] = []
        bus.subscribe(EventType.CKYC_VERIFY, lambda e: ckyc.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={"user": "alice", "pan": "ABCDE1234F", "aadhaar": "123456789012"},
            )
        )
        assert len(ckyc) == 1
        assert ckyc[0].payload["user"] == "alice"

    def test_video_kyc_initiated_emitted(self) -> None:
        bus = LocalBus()
        vkyc: list[Event] = []
        bus.subscribe("kyc.video_initiated", lambda e: vkyc.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={"user": "alice", "pan": "ABCDE1234F", "aadhaar": "123456789012"},
            )
        )
        assert len(vkyc) == 1

    def test_can_query_kyc_status(self) -> None:
        bus = LocalBus()
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={"user": "query_user", "pan": "ABCDE1234F", "aadhaar": "123456789012"},
            )
        )
        status = svc.get_kyc_status("query_user")
        assert status is not None
        assert status["kyc_status"] == "format_verified"
        assert status["pan"] == "ABCDE1234F"
        assert status["aadhaar"] == "9012"

    def test_ckyc_verified_updates_record(self) -> None:
        bus = LocalBus()
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={"user": "ckyc_user", "pan": "ABCDE1234F", "aadhaar": "123456789012"},
            )
        )
        svc.handle(
            Event(
                event_type=EventType.CKYC_VERIFIED,
                source="credit_bureau",
                payload={
                    "user": "ckyc_user",
                    "status": "verified",
                },
            )
        )
        status = svc.get_kyc_status("ckyc_user")
        assert status is not None
        assert status["ckyc_status"] == "verified"

    def test_health_check_returns_counts(self) -> None:
        bus = LocalBus()
        svc = compliance(bus=bus)
        bus.start()
        health = svc.health_check()
        assert "aml_blocklist_entries" in health
        assert "kyc_records" in health
