"""KYC/AML compliance workflows for Indian fintech onboarding."""

from __future__ import annotations

from ulu.domain.users import AmlStatus, KycStatus, User


class KycAmlService:
    """Identity verification and AML screening service."""

    def verify_kyc(self, user: User, pan_number: str, aadhaar_hash: str) -> KycStatus:
        """Verifies user identity against government databases."""
        if not pan_number or not aadhaar_hash:
            user.kyc_status = KycStatus.REJECTED
            return KycStatus.REJECTED
        raise NotImplementedError(
            "KYC verification requires integration with PAN/Aadhaar APIs. "
            "This stub accepts any non-empty input, which is not safe for production."
        )

    def screen_aml(self, user: User, watchlist_hit: bool = False) -> AmlStatus:
        """Screens user against AML watchlists."""
        if watchlist_hit:
            user.aml_status = AmlStatus.FROZEN
            return AmlStatus.FROZEN
        user.aml_status = AmlStatus.CLEAR
        return AmlStatus.CLEAR

    def is_compliant(self, user: User) -> bool:
        """Returns True only if KYC verified and AML clear."""
        return user.is_compliant()
