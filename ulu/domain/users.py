"""User domain models, roles, and identity status enums."""

from __future__ import annotations

import enum


class UserRole(enum.Enum):
    SEED = "seed"
    LSP = "lsp"
    SUB_SPONSOR = "sub_sponsor"
    BORROWER = "borrower"


class KycStatus(enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AmlStatus(enum.Enum):
    CLEAR = "clear"
    FLAGGED = "flagged"
    FROZEN = "frozen"


class User:
    """Domain representation of a network participant."""

    def __init__(
        self,
        identifier: str,
        role: UserRole,
        kyc_status: KycStatus = KycStatus.PENDING,
        aml_status: AmlStatus = AmlStatus.CLEAR,
    ) -> None:
        self.identifier = identifier
        self.role = role
        self.kyc_status = kyc_status
        self.aml_status = aml_status

    def is_compliant(self) -> bool:
        """Returns True if user passes KYC and AML gates."""
        return self.kyc_status == KycStatus.VERIFIED and self.aml_status == AmlStatus.CLEAR
