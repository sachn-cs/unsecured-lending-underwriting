"""Unit tests for API validators."""

from __future__ import annotations

import pytest

from ulu.api.schemas import KycRequest
from ulu.api.validators import validate_aadhaar, validate_pan


class TestValidators:
    def test_valid_pan(self) -> None:
        assert validate_pan("ABCDE1234F") is True

    def test_invalid_pan_short(self) -> None:
        assert validate_pan("ABC") is False

    def test_invalid_pan_bad_format(self) -> None:
        assert validate_pan("1234512345") is False

    def test_valid_aadhaar(self) -> None:
        assert validate_aadhaar("123456789012") is True

    def test_invalid_aadhaar_short(self) -> None:
        assert validate_aadhaar("12345") is False

    def test_invalid_aadhaar_non_digit(self) -> None:
        assert validate_aadhaar("12345678901A") is False


class TestKycRequest:
    def test_valid_pan(self) -> None:
        req = KycRequest(borrower_id="b1", pan_number="ABCDE1234F")
        assert req.pan_number == "ABCDE1234F"

    def test_invalid_pan(self) -> None:
        with pytest.raises(ValueError, match="invalid PAN"):
            KycRequest(borrower_id="b1", pan_number="BAD")

    def test_valid_aadhaar(self) -> None:
        req = KycRequest(borrower_id="b1", aadhaar_hash="123456789012")
        assert req.aadhaar_hash == "123456789012"

    def test_invalid_aadhaar(self) -> None:
        with pytest.raises(ValueError, match="invalid Aadhaar"):
            KycRequest(borrower_id="b1", aadhaar_hash="12345")

    def test_empty_fields_allowed(self) -> None:
        req = KycRequest(borrower_id="b1")
        assert req.pan_number == ""
        assert req.aadhaar_hash == ""
