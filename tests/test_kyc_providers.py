"""Tests for the KYC provider integration clients."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from underwrite.services.kyc.aadhaar import AadhaarEKycClient
from underwrite.services.kyc.base import Verdict
from underwrite.services.kyc.cibil import CibilBureauClient
from underwrite.services.kyc.ckyc import CkycSearchClient
from underwrite.services.kyc.factory import Config
from underwrite.services.kyc.pan import PanVerificationClient


class TestPanVerificationClient:
    def test_unconfigured_returns_error(self) -> None:
        client = PanVerificationClient()
        result = client.verify("ABCDE1234F", name="John", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "not configured" in result.error

    def test_malformed_pan_returns_mismatch(self) -> None:
        client = PanVerificationClient(client_id="id", client_secret="secret")
        result = client.verify("NOT-A-PAN", consent="Y")
        assert result.verdict == Verdict.MISMATCH

    def test_missing_consent_returns_rejected(self) -> None:
        client = PanVerificationClient(client_id="id", client_secret="secret")
        result = client.verify("ABCDE1234F", consent="")
        assert result.verdict == Verdict.REJECTED

    def test_uppercases_and_signs(self) -> None:
        client = PanVerificationClient(client_id="id", client_secret="secret")
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
            result = client.verify("abcde1234f", name="John", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.reference == "req-1"
        assert result.details["pan"] == "ABCDE1234F"
        assert result.details["first_name"] == "JOHN"

    def test_invalid_status_returns_rejected(self) -> None:
        client = PanVerificationClient(client_id="id", client_secret="secret")
        with patch.object(
            client,
            "http_post",
            return_value={"status": "DEACTIVATED"},
        ):
            result = client.verify("ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.REJECTED

    def test_transport_error_returns_error(self) -> None:
        client = PanVerificationClient(client_id="id", client_secret="secret")
        with patch.object(
            client,
            "http_post",
            side_effect=RuntimeError("network down"),
        ):
            result = client.verify("ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "network down" in result.error


class TestAadhaarEKycClient:
    def test_unconfigured_returns_error(self) -> None:
        client = AadhaarEKycClient()
        result = client.verify("123456789012", otp="1234", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "not configured" in result.error

    def test_malformed_aadhaar_returns_mismatch(self) -> None:
        client = AadhaarEKycClient(kua_id="k", kua_license_key="l")
        result = client.verify("123", otp="1234", consent="Y")
        assert result.verdict == Verdict.MISMATCH

    def test_missing_otp_returns_error(self) -> None:
        client = AadhaarEKycClient(kua_id="k", kua_license_key="l")
        result = client.verify("123456789012", otp="", consent="Y")
        assert result.verdict == Verdict.ERROR

    def test_authenticated_response(self) -> None:
        client = AadhaarEKycClient(kua_id="k", kua_license_key="l")
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
            result = client.verify("123456789012", otp="1234", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.reference == "ref-1"
        assert result.details["name"] == "John"

    def test_failed_response(self) -> None:
        client = AadhaarEKycClient(kua_id="k", kua_license_key="l")
        with patch.object(
            client,
            "send_kyc_request",
            return_value={"status": "N", "message": "bad otp"},
        ):
            result = client.verify("123456789012", otp="1234", consent="Y")
        assert result.verdict == Verdict.MISMATCH
        assert result.error == "bad otp"


class TestCibilBureauClient:
    def test_unconfigured_returns_error(self) -> None:
        client = CibilBureauClient()
        result = client.verify("C-1", name="John", pan="ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.ERROR
        assert "not configured" in result.error

    def test_missing_consent_returns_rejected(self) -> None:
        client = CibilBureauClient(partner_id="p", partner_key="k")
        result = client.verify("C-1", name="John", pan="ABCDE1234F", consent="")
        assert result.verdict == Verdict.REJECTED

    def test_pull_with_score(self) -> None:
        client = CibilBureauClient(partner_id="p", partner_key="k")
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
            result = client.verify("C-1", name="John", pan="ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.details["score"] == 750
        assert result.details["score_band"] == "Excellent"

    def test_no_score_returns_not_found(self) -> None:
        client = CibilBureauClient(partner_id="p", partner_key="k")
        with patch.object(
            client,
            "request_score",
            return_value={"request_id": "req-1", "message": "no record"},
        ):
            result = client.verify("C-1", name="John", pan="ABCDE1234F", consent="Y")
        assert result.verdict == Verdict.NOT_FOUND


class TestCkycSearchClient:
    def test_unconfigured_returns_error(self) -> None:
        client = CkycSearchClient()
        result = client.verify("CKYC123", consent="Y")
        assert result.verdict == Verdict.ERROR

    def test_invalid_identifier_type(self) -> None:
        client = CkycSearchClient(search_provider_id="p", search_provider_key="k")
        result = client.verify("X", identifier_type="phone", consent="Y")
        assert result.verdict == Verdict.ERROR

    def test_hit(self) -> None:
        client = CkycSearchClient(search_provider_id="p", search_provider_key="k")
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
            result = client.verify("110000001234", consent="Y")
        assert result.verdict == Verdict.VERIFIED
        assert result.details["ckyc_number"] == "110000001234"

    def test_miss(self) -> None:
        client = CkycSearchClient(search_provider_id="p", search_provider_key="k")
        with patch.object(
            client,
            "request_search",
            return_value={"request_id": "req-1", "kyc_status": "NOT_FOUND"},
        ):
            result = client.verify("110000001234", consent="Y")
        assert result.verdict == Verdict.NOT_FOUND


class TestKycProviderConfig:
    def test_default_factory_resolves_all_four(self) -> None:
        config = Config()
        providers = config.all(secrets=None)
        assert set(providers) == {"pan", "aadhaar", "cibil", "ckyc"}
        for name, p in providers.items():
            assert p.is_configured() is False, name

    def test_factory_pulls_from_secrets(self) -> None:
        config = Config()
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
        providers = config.all(secrets=secrets)
        assert providers["pan"].is_configured() is True
        assert providers["aadhaar"].is_configured() is True
        assert providers["cibil"].is_configured() is True
        assert providers["ckyc"].is_configured() is True
