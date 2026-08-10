"""Factory and config for KYC provider clients."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from underwrite.services.kyc.aadhaar import (
    PRODUCTION_BASE_URL as AADHAAR_PRODUCTION_BASE_URL,
)
from underwrite.services.kyc.aadhaar import (
    SANDBOX_BASE_URL as AADHAAR_SANDBOX_BASE_URL,
)
from underwrite.services.kyc.aadhaar import (
    AadhaarEKycClient,
)
from underwrite.services.kyc.base import Provider
from underwrite.services.kyc.cibil import (
    PRODUCTION_BASE_URL as CIBIL_PRODUCTION_BASE_URL,
)
from underwrite.services.kyc.cibil import (
    SANDBOX_BASE_URL as CIBIL_SANDBOX_BASE_URL,
)
from underwrite.services.kyc.cibil import (
    CibilBureauClient,
)
from underwrite.services.kyc.ckyc import (
    PRODUCTION_BASE_URL as CKYC_PRODUCTION_BASE_URL,
)
from underwrite.services.kyc.ckyc import (
    SANDBOX_BASE_URL as CKYC_SANDBOX_BASE_URL,
)
from underwrite.services.kyc.ckyc import (
    CkycSearchClient,
)
from underwrite.services.kyc.pan import (
    PRODUCTION_BASE_URL as PAN_PRODUCTION_BASE_URL,
)
from underwrite.services.kyc.pan import (
    SANDBOX_BASE_URL as PAN_SANDBOX_BASE_URL,
)
from underwrite.services.kyc.pan import (
    PanVerificationClient,
)

if TYPE_CHECKING:
    from underwrite.secrets import Manager


class Config(BaseModel):
    """Top-level config block for the KYC provider integrations.

    The block lives under ``config.kyc_providers`` in the runtime
    configuration. Secret-shaped fields are read from the secrets
    backend at startup; the config file on disk only carries
    non-sensitive URLs and timeouts.
    """

    pan_client_id: str = ""
    pan_client_secret: str = ""
    pan_api_base_url: str = ""

    aadhaar_kua_id: str = ""
    aadhaar_kua_license_key: str = ""
    aadhaar_api_base_url: str = ""

    cibil_partner_id: str = ""
    cibil_partner_key: str = ""
    cibil_api_base_url: str = ""

    ckyc_search_provider_id: str = ""
    ckyc_search_provider_key: str = ""
    ckyc_api_base_url: str = ""

    timeout_seconds: int = Field(default=30, ge=1)

    def resolve_pan(self, secrets: Manager | None) -> PanVerificationClient:
        client_id = self.pan_client_id
        client_secret = self.pan_client_secret
        if secrets is not None:
            if not client_id:
                client_id = secrets.get("underwrite/pan/client_id") or ""
            if not client_secret:
                client_secret = secrets.get("underwrite/pan/client_secret") or ""
        base = self.pan_api_base_url or PAN_PRODUCTION_BASE_URL
        if not (self.pan_api_base_url or os.environ.get("UNDERWRITE_PAN_PRODUCTION")):
            base = PAN_SANDBOX_BASE_URL
        return PanVerificationClient(
            client_id=client_id,
            client_secret=client_secret,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def resolve_aadhaar(self, secrets: Manager | None) -> AadhaarEKycClient:
        kua_id = self.aadhaar_kua_id
        kua_license = self.aadhaar_kua_license_key
        if secrets is not None:
            if not kua_id:
                kua_id = secrets.get("underwrite/aadhaar/kua_id") or ""
            if not kua_license:
                kua_license = secrets.get("underwrite/aadhaar/kua_license_key") or ""
        base = self.aadhaar_api_base_url or AADHAAR_PRODUCTION_BASE_URL
        if not (self.aadhaar_api_base_url or os.environ.get("UNDERWRITE_AADHAAR_PRODUCTION")):
            base = AADHAAR_SANDBOX_BASE_URL
        return AadhaarEKycClient(
            kua_id=kua_id,
            kua_license_key=kua_license,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def resolve_cibil(self, secrets: Manager | None) -> CibilBureauClient:
        partner_id = self.cibil_partner_id
        partner_key = self.cibil_partner_key
        if secrets is not None:
            if not partner_id:
                partner_id = secrets.get("underwrite/cibil/partner_id") or ""
            if not partner_key:
                partner_key = secrets.get("underwrite/cibil/partner_key") or ""
        base = self.cibil_api_base_url or CIBIL_PRODUCTION_BASE_URL
        if not (self.cibil_api_base_url or os.environ.get("UNDERWRITE_CIBIL_PRODUCTION")):
            base = CIBIL_SANDBOX_BASE_URL
        return CibilBureauClient(
            partner_id=partner_id,
            partner_key=partner_key,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def resolve_ckyc(self, secrets: Manager | None) -> CkycSearchClient:
        sp_id = self.ckyc_search_provider_id
        sp_key = self.ckyc_search_provider_key
        if secrets is not None:
            if not sp_id:
                sp_id = secrets.get("underwrite/ckyc/search_provider_id") or ""
            if not sp_key:
                sp_key = secrets.get("underwrite/ckyc/search_provider_key") or ""
        base = self.ckyc_api_base_url or CKYC_PRODUCTION_BASE_URL
        if not (self.ckyc_api_base_url or os.environ.get("UNDERWRITE_CKYC_PRODUCTION")):
            base = CKYC_SANDBOX_BASE_URL
        return CkycSearchClient(
            search_provider_id=sp_id,
            search_provider_key=sp_key,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def all(self, secrets: Manager | None) -> dict[str, Provider]:
        """Return a name → client map for all four providers."""
        return {
            "pan": self.resolve_pan(secrets),
            "aadhaar": self.resolve_aadhaar(secrets),
            "cibil": self.resolve_cibil(secrets),
            "ckyc": self.resolve_ckyc(secrets),
        }
