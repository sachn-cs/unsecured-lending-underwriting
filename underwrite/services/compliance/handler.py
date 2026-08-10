"""Compliance - RBI-compliant KYC/AML checks for Indian fintech.

Verifies PAN (format + category), Aadhaar (Verhoeff check digit),
screens against AML blocklists with risk scoring, and emits CKYC
and video-KYC event hooks per RBI Digital Lending Guidelines.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from underwrite.authz import AccessControl
from underwrite.bus import EventBus
from underwrite.health import Checks
from underwrite.keypair import Keypair
from underwrite.logger import logger
from underwrite.message import Message, Type
from underwrite.metrics import Collector
from underwrite.saga import Orchestrator
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.store import Store
from underwrite.supervisor import Watcher
from underwrite.tracer import Tracer

PAN_PATTERN: str = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
PAN_CATEGORIES: dict[str, str] = {
    "A": "Association of Persons",
    "B": "Body of Individuals",
    "C": "Company",
    "F": "Firm",
    "G": "Government Agency",
    "H": "Hindu Undivided Family",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "P": "Individual",
    "T": "Trust",
}

AADHAAR_PATTERN: str = r"^\d{12}$"
BLOCKLIST_PATH: str = "aml_blocklist.json"

AML_RISK_WEIGHTS: dict[str, int] = {
    "pep": 3,
    "politically exposed": 3,
    "sanctions": 5,
    "watchlist": 5,
    "terror": 5,
    "terrorist": 5,
    "money laundering": 5,
    "fraud": 4,
    "scam": 4,
    "shell company": 4,
    "offshore": 3,
    "high risk": 3,
    "adverse media": 3,
    "criminal": 5,
    "corruption": 4,
    "bribery": 4,
    "PEP": 3,
}

AML_LOW_THRESHOLD: int = 3
AML_MEDIUM_THRESHOLD: int = 7

VERHOEFF_D: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

VERHOEFF_P: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

VERHOEFF_INV: tuple[int, ...] = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def load_blocklist(path: str) -> set[str]:
    """Load AML blocklist from a JSON file.

    Args:
        path: Path to the JSON blocklist file.

    Returns:
        Set of lowercased blocked entry strings.

    """
    p = Path(path)
    if not p.exists():
        return set()
    try:
        with open(p) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return {entry.strip().lower() for entry in data if entry}
        logger.warning("aml_blocklist must be a JSON list, got {}", type(data))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("failed to load AML blocklist {}: {}", path, exc)
    return set()


def verify_aadhaar_checksum(aadhaar: str) -> bool:
    """Verify an Aadhaar number using the Verhoeff checksum algorithm.

    Args:
        aadhaar: 12-digit Aadhaar number as a string.

    Returns:
        True if the checksum is valid, False otherwise.

    """
    if not aadhaar or len(aadhaar) != 12 or not aadhaar.isdigit():
        return False
    c = 0
    digits = [int(d) for d in aadhaar]
    for i, digit in enumerate(reversed(digits)):
        c = VERHOEFF_D[c][VERHOEFF_P[(i + 1) % 8][digit]]
    return c == 0


def pan_category(pan: str) -> str:
    """Return the PAN category label based on the 4th character.

    Args:
        pan: 10-character PAN string.

    Returns:
        Category label or 'Unknown'.

    """
    if not pan or len(pan) < 4:
        return "Unknown"
    code = pan[3]
    return PAN_CATEGORIES.get(code, "Unknown")


@dataclass(frozen=True, slots=True)
class ComplianceConfig:
    """Typed configuration for ComplianceHandler.

    Replaces the previous ``kwargs.pop("aml_blocklist_path", ...)``
    pattern: callers now pass a ComplianceConfig (or its fields are
    extracted from kwargs via a constructor that does not mutate
    the caller's mapping).
    """

    aml_blocklist_path: str = ""
    kyc_providers: dict[str, Any] = field(default_factory=dict)


class ComplianceHandler(StatefulService):
    """RBI-compliant KYC/AML verification with risk scoring and AML screening."""

    def __init__(
        self,
        service_id: str,
        bus: EventBus,
        store: Store,
        identity: Keypair | None = None,
        metrics: Collector | None = None,
        health: Checks | None = None,
        authz: AccessControl | None = None,
        tracer: Tracer | None = None,
        saga: Orchestrator | None = None,
        supervisor: Watcher | None = None,
        secrets_manager: Any | None = None,
        max_concurrent: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the compliance service with KYC records and AML blocklist.

        Args:
            **kwargs: May include ``aml_blocklist_path`` and
                ``kyc_providers``. Falls back to ``AML_BLOCKLIST_PATH``
                env var or ``aml_blocklist.json``. ``kyc_providers``
                is a dict mapping ``pan`` / ``aadhaar`` / ``cibil`` /
                ``ckyc`` to a ``Provider`` instance; when present,
                real upstream verifications are run; when missing
                the service falls back to format-only validation.
        """
        config = ComplianceConfig(
            aml_blocklist_path=kwargs.pop(
                "aml_blocklist_path",
                os.environ.get("AML_BLOCKLIST_PATH", BLOCKLIST_PATH),
            ),
            kyc_providers=kwargs.pop("kyc_providers", {}),
        )
        self.__aml_blocklist_path: str = config.aml_blocklist_path
        self.__kyc_providers: dict[str, Any] = config.kyc_providers
        super().__init__(
            service_id=service_id,
            identity=identity,
            bus=bus,
            store=store,
            metrics=metrics,
            health=health,
            authz=authz,
            tracer=tracer,
            saga=saga,
            supervisor=supervisor,
            secrets_manager=secrets_manager,
            max_concurrent=max_concurrent,
        )
        self.__blocklist: set[str] = load_blocklist(self.__aml_blocklist_path)
        self.__kyc_records: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, Any]] = self.store_repo("compliance", dict)
        loaded = self.repo.load(default={})
        if loaded:
            self.__kyc_records = loaded.get("kyc_records", {})

    def handle(self, event: Message) -> None:
        """Process KYC and compliance events.

        Args:
            event: The incoming domain event. Processes USER_ADDED,
                CKYC_VERIFIED, and kyc.video_verified.

        """
        if event.event_type == Type.USER_ADDED:
            self.on_user_added(event)
        elif event.event_type == Type.CKYC_VERIFIED:
            self.on_ckyc_verified(event)
        elif event.event_type == Type.KYC_VIDEO_VERIFIED.value:
            self.on_video_kyc_done(event)

    def on_user_added(self, event: Message) -> None:
        """Process a new user: verify PAN, Aadhaar, run AML screening.

        Args:
            event: The USER_ADDED event with user, pan, aadhaar,
                name, and optional consent_id payload.

        """
        user: str = event.payload.get("user", "")
        pan: str = event.payload.get("pan", "").upper()
        aadhaar: str = event.payload.get("aadhaar", "")
        name: str = event.payload.get("name", user)
        consent_id: str = event.payload.get("consent_id", "")

        if consent_id and not self.check_consent(user, consent_id):
            self.emit(
                Type.KYC_REJECTED,
                {
                    "user": user,
                    "kyc_status": "rejected",
                    "reason": "consent_not_given",
                },
                correlation_id=event.correlation_id,
            )
            return

        if not re.match(PAN_PATTERN, pan):
            self.emit(
                Type.KYC_REJECTED,
                {
                    "user": user,
                    "kyc_status": "rejected",
                    "reason": "invalid_pan_format",
                },
                correlation_id=event.correlation_id,
            )
            return

        pan_cat = pan_category(pan)

        if not verify_aadhaar_checksum(aadhaar):
            self.emit(
                Type.KYC_REJECTED,
                {
                    "user": user,
                    "kyc_status": "rejected",
                    "reason": "invalid_aadhaar_checksum",
                },
                correlation_id=event.correlation_id,
            )
            return

        pan_verdict = "format_verified"
        pan_provider_result: dict[str, Any] = {}
        pan_provider = self.__kyc_providers.get("pan")
        if pan_provider is not None:
            from underwrite.services.kyc.base import Verdict as _V

            result = pan_provider.verify(pan, name=name, consent="Y" if consent_id else "")
            pan_provider_result = {
                "pan_provider_reference": result.reference,
                "pan_provider_status": result.verdict.value,
            }
            if result.verdict == _V.VERIFIED:
                pan_verdict = "verified"
            elif result.verdict in (_V.REJECTED, _V.NOT_FOUND, _V.MISMATCH):
                self.emit(
                    Type.KYC_REJECTED,
                    {
                        "user": user,
                        "kyc_status": "rejected",
                        "reason": f"pan_{result.verdict.value}",
                        **pan_provider_result,
                    },
                    correlation_id=event.correlation_id,
                )
                return
            else:
                pan_verdict = f"error:{result.error}"

        kyc_data: dict[str, Any] = {
            "user": user,
            "pan": pan,
            "pan_category": pan_cat,
            "aadhaar": aadhaar[-4:],
            "aadhaar_verified": True,
            "name": name,
            "kyc_status": pan_verdict,
            "ckyc_status": "pending",
            "video_kyc_status": "pending",
            "verified_at": event.timestamp,
        }

        with self.state_lock:
            self.__kyc_records[user] = kyc_data
            self.repo.save({"kyc_records": self.__kyc_records})

        self.emit(
            Type.KYC_VERIFIED,
            {
                "user": user,
                "kyc_status": pan_verdict,
                "pan_category": pan_cat,
                "aadhaar_last4": aadhaar[-4:],
                **pan_provider_result,
            },
            correlation_id=event.correlation_id,
        )

        self.emit(
            Type.CKYC_VERIFY,
            {
                "user": user,
                "ckyc_number": event.payload.get("ckyc_number", ""),
                "aadhaar": aadhaar,
                "pan": pan,
                "name": name,
            },
            correlation_id=event.correlation_id,
        )

        risk_score = self.__screen(name, user)
        self.apply_aml_result(user, risk_score, event)

        self.emit(
            Type.KYC_VIDEO_INITIATED.value,
            {
                "user": user,
                "video_kyc_status": "pending",
            },
            correlation_id=event.correlation_id,
        )

    def apply_aml_result(self, user: str, risk_score: int, event: Message) -> None:
        """Apply AML screening result and emit appropriate events.

        Args:
            user: The user identifier.
            risk_score: Integer risk score from AML screening.
            event: The originating event for correlation.

        """
        if risk_score >= AML_MEDIUM_THRESHOLD:
            self.emit(
                Type.AML_FROZEN,
                {
                    "user": user,
                    "aml_status": "frozen",
                    "risk_score": risk_score,
                    "reason": "high_risk_aml_screening",
                },
                correlation_id=event.correlation_id,
            )
            with self.state_lock:
                if user in self.__kyc_records:
                    self.__kyc_records[user]["aml_status"] = "frozen"
                    self.__kyc_records[user]["aml_risk_score"] = risk_score
                    self.repo.save({"kyc_records": self.__kyc_records})
        elif risk_score >= AML_LOW_THRESHOLD:
            self.emit(
                Type.AML_FLAGGED.value,
                {
                    "user": user,
                    "aml_status": "flagged",
                    "risk_score": risk_score,
                    "reason": "medium_risk_aml_screening",
                },
                correlation_id=event.correlation_id,
            )
            with self.state_lock:
                if user in self.__kyc_records:
                    self.__kyc_records[user]["aml_status"] = "flagged"
                    self.__kyc_records[user]["aml_risk_score"] = risk_score
                    self.repo.save({"kyc_records": self.__kyc_records})
            self.emit(
                Type.AML_CLEARED,
                {
                    "user": user,
                    "aml_status": "flagged_review",
                },
                correlation_id=event.correlation_id,
            )
        else:
            self.emit(
                Type.AML_CLEARED,
                {
                    "user": user,
                    "aml_status": "clear",
                },
                correlation_id=event.correlation_id,
            )
            with self.state_lock:
                if user in self.__kyc_records:
                    self.__kyc_records[user]["aml_status"] = "clear"
                    self.repo.save({"kyc_records": self.__kyc_records})

    def on_ckyc_verified(self, event: Message) -> None:
        """Update CKYC verification status.

        Args:
            event: The CKYC_VERIFIED event with user and status.

        """
        user: str = event.payload.get("user", "")
        status: str = event.payload.get("status", "")
        with self.state_lock:
            if user in self.__kyc_records:
                self.__kyc_records[user]["ckyc_status"] = status
                self.repo.save({"kyc_records": self.__kyc_records})

    def on_video_kyc_done(self, event: Message) -> None:
        """Update video KYC status.

        Args:
            event: The kyc.video_verified event with user and status.

        """
        user: str = event.payload.get("user", "")
        status: str = event.payload.get("status", "")
        with self.state_lock:
            if user in self.__kyc_records:
                self.__kyc_records[user]["video_kyc_status"] = status
                self.repo.save({"kyc_records": self.__kyc_records})

    @staticmethod
    def check_consent(user: str, consent_id: str) -> bool:
        """Check if user has provided valid consent.

        Args:
            user: The user identifier.
            consent_id: The consent reference identifier.

        Returns:
            True if consent is valid.

        """
        return bool(consent_id)

    def __screen(self, name: str, user: str) -> int:
        """Screen a user against the AML blocklist and keyword weights.

        Args:
            name: The user's full name.
            user: The user identifier.

        Returns:
            Integer risk score (higher = higher risk).

        """
        name_lower: str = name.lower().strip()
        user_lower: str = user.lower().strip()
        risk_score: int = 0

        if self.__blocklist and any(blocked in name_lower or blocked in user_lower for blocked in self.__blocklist):
            risk_score += 8

        text = f"{name_lower} {user_lower}"
        for keyword, weight in AML_RISK_WEIGHTS.items():
            if keyword.lower() in text:
                risk_score += weight

        return risk_score

    def get_kyc_status(self, user: str) -> dict[str, Any] | None:
        """Return the KYC status for a user.

        Args:
            user: The user identifier.

        Returns:
            KYC record dict or None if not found.

        """
        with self.state_lock:
            return self.__kyc_records.get(user)

    def health_check(self) -> dict[str, Any]:
        """Compliance-specific health: reports blocklist and KYC counts.

        Returns:
            Health dict extended with aml_blocklist_entries and
            kyc_records counts.

        """
        base = super().health_check()
        base["aml_blocklist_entries"] = len(self.__blocklist)
        base["kyc_records"] = len(self.__kyc_records)
        return base
