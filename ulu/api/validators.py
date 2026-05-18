"""Input validators for regulated Indian fintech data formats."""

from __future__ import annotations

import re

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
AADHAAR_PATTERN = re.compile(r"^\d{12}$")


def validate_pan(pan: str) -> bool:
    """Returns True if the PAN string matches the Indian Income Tax format."""
    return bool(PAN_PATTERN.match(pan))


def validate_aadhaar(aadhaar: str) -> bool:
    """Returns True if the Aadhaar number is exactly 12 digits."""
    return bool(AADHAAR_PATTERN.match(aadhaar))
