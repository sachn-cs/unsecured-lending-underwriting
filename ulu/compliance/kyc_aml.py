"""KYC/AML compliance workflows for Indian fintech onboarding."""

from __future__ import annotations

import asyncio

from ulu.api.validators import validate_pan
from ulu.domain.events import AmlStatusChangeEvent, KycStatusChangeEvent
from ulu.domain.users import AmlStatus, KycStatus, User
from ulu.infra.circuit_breaker import kyc_breaker
from ulu.infra.logging import logger


class KycAmlService:
    """Identity verification and AML screening service."""

    VALID_KYC_TRANSITIONS: dict[KycStatus, set[KycStatus]] = {
        KycStatus.PENDING: {KycStatus.VERIFIED, KycStatus.REJECTED},
        KycStatus.VERIFIED: {KycStatus.EXPIRED},
        KycStatus.REJECTED: {KycStatus.PENDING},
        KycStatus.EXPIRED: {KycStatus.PENDING},
    }

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def _verify_kyc_stub(self, user: User, pan_number: str, aadhaar_hash: str) -> KycStatus:
        if not validate_pan(pan_number):
            self.transition_kyc(user, KycStatus.REJECTED, "invalid_pan")
            return KycStatus.REJECTED
        if not aadhaar_hash:
            self.transition_kyc(user, KycStatus.REJECTED, "missing_aadhaar")
            return KycStatus.REJECTED
        raise NotImplementedError(
            "KYC verification requires integration with PAN/Aadhaar APIs. "
            "This stub accepts any non-empty input, which is not safe for production."
        )

    def verify_kyc(self, user: User, pan_number: str, aadhaar_hash: str) -> KycStatus:
        """Verifies user identity against government databases."""
        return kyc_breaker(self._verify_kyc_stub)(user, pan_number, aadhaar_hash)

    async def verify_kyc_async(self, user: User, pan_number: str, aadhaar_hash: str) -> KycStatus:
        """Async wrapper for KYC verification with timeout."""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, self.verify_kyc, user, pan_number, aadhaar_hash),
            timeout=self.timeout,
        )

    def transition_kyc(self, user: User, new_status: KycStatus, reason: str = "") -> KycStatusChangeEvent | None:
        """Transitions KYC status if valid; emits audit event."""
        old_status = user.kyc_status
        if old_status == new_status:
            return None
        if new_status not in self.VALID_KYC_TRANSITIONS.get(old_status, set()):
            raise ValueError(f"invalid KYC transition: {old_status.value} -> {new_status.value}")
        user.kyc_status = new_status
        event = KycStatusChangeEvent(
            event_type="kyc_status_change",
            payload={
                "user_id": user.identifier,
                "old_status": old_status.value,
                "new_status": new_status.value,
                "reason": reason,
            },
            user_id=user.identifier,
            old_status=old_status.value,
            new_status=new_status.value,
            reason=reason,
        )
        logger.info("kyc_status_changed", user_id=user.identifier, old=old_status.value, new=new_status.value)
        return event

    def screen_aml(self, user: User, watchlist_hit: bool = False) -> tuple[AmlStatus, AmlStatusChangeEvent | None]:
        """Screens user against AML watchlists and emits audit event on change."""
        old_status = user.aml_status
        if watchlist_hit:
            user.aml_status = AmlStatus.FROZEN
        else:
            user.aml_status = AmlStatus.CLEAR

        if old_status == user.aml_status:
            return user.aml_status, None

        event = AmlStatusChangeEvent(
            event_type="aml_status_change",
            payload={
                "user_id": user.identifier,
                "old_status": old_status.value,
                "new_status": user.aml_status.value,
                "reason": "watchlist_hit" if watchlist_hit else "screening_clear",
            },
            user_id=user.identifier,
            old_status=old_status.value,
            new_status=user.aml_status.value,
            reason="watchlist_hit" if watchlist_hit else "screening_clear",
        )
        logger.info("aml_status_changed", user_id=user.identifier, old=old_status.value, new=user.aml_status.value)
        return user.aml_status, event

    def is_compliant(self, user: User) -> bool:
        """Returns True only if KYC verified and AML clear."""
        return user.is_compliant()
