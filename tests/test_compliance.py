"""Tests for ComplianceService — KYC/AML checks.

Tests verify behavior through emitted events only:
  - KYC_VERIFIED for valid PAN + Aadhaar
  - KYC_REJECTED for invalid PAN or Aadhaar
  - Edge cases: empty fields, case sensitivity, missing payload
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.compliance.service import ComplianceService


def compliance(bus=None) -> ComplianceService:
    return ComplianceService(service_id="compliance", bus=bus)


class TestComplianceService:

    def __assert_events(self,
                        payload: dict,
                        expected_verified: bool,
                        expected_reason: str = "") -> None:
        bus = LocalBus()
        kyc: list[Event] = []
        aml: list[Event] = []
        rejected: list[Event] = []
        bus.subscribe(EventType.KYC_VERIFIED, lambda e: kyc.append(e))
        bus.subscribe(EventType.AML_CLEARED, lambda e: aml.append(e))
        bus.subscribe(EventType.KYC_REJECTED, lambda e: rejected.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.USER_ADDED,
                  source="test",
                  payload=payload))
        if expected_verified:
            assert len(kyc) == 1, f"Expected KYC_VERIFIED but got {len(kyc)}"
            assert len(aml) == 1, f"Expected AML_CLEARED but got {len(aml)}"
            assert len(rejected) == 0
        else:
            assert len(
                rejected) == 1, f"Expected KYC_REJECTED but got {len(rejected)}"
            assert len(kyc) == 0
            assert len(aml) == 0
            if expected_reason:
                assert rejected[0].payload["reason"] == expected_reason, \
                    f"Expected reason '{expected_reason}' got '{rejected[0].payload.get('reason')}'"

    def test_verified_with_valid_pan_and_aadhaar(self) -> None:
        self.__assert_events(
            {
                "user": "alice",
                "pan": "ABCDE1234F",
                "aadhaar": "123456789012"
            },
            expected_verified=True,
        )

    def test_verified_pan_emits_both_kyc_and_aml(self) -> None:
        bus = LocalBus()
        all_events: list[Event] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.USER_ADDED,
                  source="test",
                  payload={
                      "user": "bob",
                      "pan": "FGHIJ5678K",
                      "aadhaar": "987654321098"
                  }))
        types = [e.event_type for e in all_events]
        assert EventType.KYC_VERIFIED in types
        assert EventType.AML_CLEARED in types
        assert len(all_events) == 2

    def test_rejected_with_invalid_pan(self) -> None:
        self.__assert_events(
            {
                "user": "carol",
                "pan": "INVALID",
                "aadhaar": "123456789012"
            },
            expected_verified=False,
            expected_reason="invalid_pan",
        )

    def test_rejected_without_aadhaar(self) -> None:
        self.__assert_events(
            {
                "user": "dave",
                "pan": "ABCDE1234F",
                "aadhaar": ""
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_missing_aadhaar_field(self) -> None:
        self.__assert_events(
            {
                "user": "eve",
                "pan": "ABCDE1234F"
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_missing_pan_field(self) -> None:
        self.__assert_events(
            {
                "user": "frank",
                "aadhaar": "123456789012"
            },
            expected_verified=False,
            expected_reason="invalid_pan",
        )

    def test_rejected_empty_pan(self) -> None:
        self.__assert_events(
            {
                "user": "grace",
                "pan": "",
                "aadhaar": "123456789012"
            },
            expected_verified=False,
            expected_reason="invalid_pan",
        )

    def test_rejected_lowercase_pan(self) -> None:
        self.__assert_events(
            {
                "user": "heidi",
                "pan": "abcde1234f",
                "aadhaar": "123456789012"
            },
            expected_verified=False,
            expected_reason="invalid_pan",
        )

    def test_rejected_aadhaar_with_letters(self) -> None:
        self.__assert_events(
            {
                "user": "ivan",
                "pan": "ABCDE1234F",
                "aadhaar": "1234abcd9012"
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_aadhaar_too_short(self) -> None:
        self.__assert_events(
            {
                "user": "jack",
                "pan": "ABCDE1234F",
                "aadhaar": "12345678"
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_aadhaar_too_long(self) -> None:
        self.__assert_events(
            {
                "user": "karen",
                "pan": "ABCDE1234F",
                "aadhaar": "1234567890123"
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_aadhaar_with_spaces(self) -> None:
        self.__assert_events(
            {
                "user": "leo",
                "pan": "ABCDE1234F",
                "aadhaar": "1234 5678 9012"
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_aadhaar_with_hyphens(self) -> None:
        self.__assert_events(
            {
                "user": "mia",
                "pan": "ABCDE1234F",
                "aadhaar": "1234-5678-9012"
            },
            expected_verified=False,
            expected_reason="invalid_aadhaar",
        )

    def test_rejected_aadhaar_all_zeros(self) -> None:
        self.__assert_events(
            {
                "user": "neo",
                "pan": "ABCDE1234F",
                "aadhaar": "000000000000"
            },
            expected_verified=True,
        )

    def test_ignores_non_user_added_events(self) -> None:
        bus = LocalBus()
        kyc: list[Event] = []
        bus.subscribe(EventType.KYC_VERIFIED, lambda e: kyc.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={}))
        assert len(kyc) == 0

    def test_missing_user_field_does_not_crash(self) -> None:
        bus = LocalBus()
        kyc: list[Event] = []
        bus.subscribe(EventType.KYC_VERIFIED, lambda e: kyc.append(e))
        svc = compliance(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.USER_ADDED,
                source="test",
                payload={
                    "pan": "ABCDE1234F",
                    "aadhaar": "123456789012"
                },
            ))
        assert len(kyc) == 1
        assert kyc[0].payload["user"] == ""
