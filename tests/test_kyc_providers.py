# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for the KYC provider integration clients."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from underwrite.services.providers import (
    Aadhar,
    Cibil,
    Ckyc,
    Pan,
    ProvidersConfig,
    Verdict,
)


class TestPan:
    def test_unconfigured_returns_error(self) -> None:
        client = Pan(pan="ABCDE1234F")
        result = client.verify(name="John", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "not configured" in result.error

    def test_malformed_pan_returns_mismatch(self) -> None:
        client = Pan(pan="NOT-A-PAN", client_id="id", client_secret="secret")
        result = client.verify(consent="Y")
        assert result.verdict == Verdict.MISMATCH

    def test_missing_consent_returns_rejected(self) -> None:
        client = Pan(pan="ABCDE1234F", client_id="id", client_secret="secret")
        result = client.verify(consent="")
        assert result.verdict == Verdict.REJECTED

    def test_uppercases_and_signs(self) -> None:
        client = Pan(pan="abcde1234f", client_id="id", client_secret="secret")
        with patch.object(
            client,
            "http_post",
            return_value={
                "request_id": "req-1",
                "status": "VALID",
                "pan_status": "ACTIVE",
                "pan_type": "Individual",
                "first_name": "JOHN",
                "last_name": "DOE",
                "aadhaar_seeding_status": "Y",
            },
        ):
            result = client.verify(name="John", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.reference == "req-1"
        assert result.details["pan"] == "ABCDE1234F"
        assert result.details["first_name"] == "JOHN"

    def test_invalid_status_returns_rejected(self) -> None:
        client = Pan(pan="ABCDE1234F", client_id="id", client_secret="secret")
        with patch.object(
            client,
            "http_post",
            return_value={"status": "DEACTIVATED"},
        ):
            result = client.verify(consent="Y")
        assert result.verdict == Verdict.REJECTED

    def test_transport_error_returns_error(self) -> None:
        client = Pan(pan="ABCDE1234F", client_id="id", client_secret="secret")
        with patch.object(
            client,
            "http_post",
            side_effect=RuntimeError("network down"),
        ):
            result = client.verify(consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "network down" in result.error


class TestAadhar:
    def test_unconfigured_returns_error(self) -> None:
        client = Aadhar(number="123456789012")
        result = client.verify(otp="1234", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "not configured" in result.error

    def test_malformed_aadhaar_returns_mismatch(self) -> None:
        client = Aadhar(number="123", kua_id="k", kua_license_key="l")
        result = client.verify(otp="1234", consent="Y")
        assert result.verdict == Verdict.MISMATCH

    def test_missing_otp_returns_error(self) -> None:
        client = Aadhar(number="123456789012", kua_id="k", kua_license_key="l")
        result = client.verify(otp="", consent="Y")
        assert result.verdict == Verdict.ERROR

    def test_authenticated_response(self) -> None:
        client = Aadhar(number="123456789012", kua_id="k", kua_license_key="l")
        with patch.object(
            client,
            "send_kyc_request",
            return_value={
                "reference_id": "ref-1",
                "status": "Y",
                "name": "John",
                "dob": "1990-01-01",
                "gender": "M",
                "address": {"pin": "560001"},
            },
        ):
            result = client.verify(otp="1234", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.reference == "ref-1"
        assert result.details["name"] == "John"

    def test_failed_response(self) -> None:
        client = Aadhar(number="123456789012", kua_id="k", kua_license_key="l")
        with patch.object(
            client,
            "send_kyc_request",
            return_value={"status": "N", "message": "bad otp"},
        ):
            result = client.verify(otp="1234", consent="Y")
        assert result.verdict == Verdict.MISMATCH
        assert result.error == "bad otp"


class TestCibil:
    def test_unconfigured_returns_error(self) -> None:
        client = Cibil(consumer_id="C-1")
        result = client.verify(name="John", pan="ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "not configured" in result.error

    def test_missing_consent_returns_rejected(self) -> None:
        client = Cibil(consumer_id="C-1", partner_id="p", partner_key="k")
        result = client.verify(name="John", pan="ABCDE1234F", consent="")
        assert result.verdict == Verdict.REJECTED

    def test_pull_with_score(self) -> None:
        client = Cibil(consumer_id="C-1", partner_id="p", partner_key="k")
        with patch.object(
            client,
            "request_score",
            return_value={
                "request_id": "req-1",
                "score": 750,
                "score_band": "Excellent",
                "tradelines": 5,
                "enquiries_last_30_days": 1,
                "defaults": [],
            },
        ):
            result = client.verify(name="John", pan="ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.details["score"] == 750
        assert result.details["score_band"] == "Excellent"

    def test_no_score_returns_not_found(self) -> None:
        client = Cibil(consumer_id="C-1", partner_id="p", partner_key="k")
        with patch.object(
            client,
            "request_score",
            return_value={"request_id": "req-1", "message": "no record"},
        ):
            result = client.verify(name="John", pan="ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.NOT_FOUND


class TestCkyc:
    def test_unconfigured_returns_error(self) -> None:
        client = Ckyc(identifier="CKYC123")
        result = client.verify(consent="Y")
        assert result.verdict == Verdict.ERROR

    def test_invalid_identifier_type(self) -> None:
        client = Ckyc(identifier="X", search_provider_id="p", search_provider_key="k")
        result = client.verify(identifier_type="phone", consent="Y")
        assert result.verdict == Verdict.ERROR

    def test_hit(self) -> None:
        client = Ckyc(identifier="110000001234", search_provider_id="p", search_provider_key="k")
        with patch.object(
            client,
            "request_search",
            return_value={
                "request_id": "req-1",
                "ckyc_number": "110000001234",
                "name": "John",
                "dob": "1990-01-01",
                "pan": "ABCDE1234F",
                "aadhaar_last4": "1234",
                "address": {"pin": "560001"},
                "image_present": True,
                "kyc_status": "VERIFIED",
            },
        ):
            result = client.verify(consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.details["ckyc_number"] == "110000001234"

    def test_miss(self) -> None:
        client = Ckyc(identifier="110000001234", search_provider_id="p", search_provider_key="k")
        with patch.object(
            client,
            "request_search",
            return_value={"request_id": "req-1", "kyc_status": "NOT_FOUND"},
        ):
            result = client.verify(consent="Y")
        assert result.verdict == Verdict.NOT_FOUND


class TestProvidersConfig:
    def test_default_resolves_unconfigured_clients(self) -> None:
        config = ProvidersConfig()
        assert config.resolve_pan("ABCDE1234F").is_configured() is False
        assert config.resolve_aadhaar("123456789012").is_configured() is False
        assert config.resolve_cibil("C-1").is_configured() is False
        assert config.resolve_ckyc("CKYC123").is_configured() is False

    def test_pulls_from_secrets(self) -> None:
        config = ProvidersConfig()
        secrets = MagicMock()
        secrets.get.side_effect = lambda k: {
            "underwrite/pan/client_id": "pan-id",
            "underwrite/pan/client_secret": "pan-secret",
            "underwrite/aadhaar/kua_id": "kua-id",
            "underwrite/aadhaar/kua_license_key": "kua-lic",
            "underwrite/cibil/partner_id": "cibil-id",
            "underwrite/cibil/partner_key": "cibil-key",
            "underwrite/ckyc/search_provider_id": "ckyc-id",
            "underwrite/ckyc/search_provider_key": "ckyc-key",
        }.get(k, "")
        assert config.resolve_pan("ABCDE1234F", secrets).is_configured() is True
        assert config.resolve_aadhaar("123456789012", secrets).is_configured() is True
        assert config.resolve_cibil("C-1", secrets).is_configured() is True
        assert config.resolve_ckyc("CKYC123", secrets).is_configured() is True
