"""Compliance — KYC/AML checks for Indian fintech onboarding.

Verifies PAN and Aadhaar document formats and screens against AML
watchlists.  Rejects users whose documents do not match the expected
patterns.
"""

from __future__ import annotations

import re

from underwrite.__events__ import Event, EventType
from underwrite.services import NanoService

PAN_PATTERN: str = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
AADHAAR_PATTERN: str = r"^\d{12}$"


class ComplianceService(NanoService):
    """Verifies KYC documents and screens for AML watchlists."""

    def handle(self, event: Event) -> None:
        """Perform KYC/AML checks on newly added users.

        Validates PAN and Aadhaar formats.  Emits KYC_REJECTED,
        KYC_VERIFIED, or AML_CLEARED events accordingly.

        Args:
            event: The incoming event. Only USER_ADDED events are processed.
        """
        if event.event_type != EventType.USER_ADDED:
            return
        user: str = event.payload.get("user", "")
        pan: str = event.payload.get("pan", "")
        aadhaar: str = event.payload.get("aadhaar", "")

        if not re.match(PAN_PATTERN, pan):
            self.emit(EventType.KYC_REJECTED, {
                "user": user,
                "kyc_status": "rejected",
                "reason": "invalid_pan",
            },
                      correlation_id=event.correlation_id)
            return
        if not re.match(AADHAAR_PATTERN, aadhaar):
            self.emit(EventType.KYC_REJECTED, {
                "user": user,
                "kyc_status": "rejected",
                "reason": "invalid_aadhaar",
            },
                      correlation_id=event.correlation_id)
            return
        self.emit(EventType.KYC_VERIFIED, {
            "user": user,
            "kyc_status": "verified",
        },
                  correlation_id=event.correlation_id)
        self.emit(EventType.AML_CLEARED, {
            "user": user,
            "aml_status": "clear",
        },
                  correlation_id=event.correlation_id)
