# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""KYC provider integrations — PAN, Aadhaar (eKYC), CIBIL, CKYC.

Each provider client implements the same ``Provider`` ABC and
returns a ``ProviderResult`` carrying a ``Verdict`` enum plus the
provider's structured response. Clients are configured through the
runtime ``Configuration`` and authenticate with provider-specific
secrets held in the configured ``Manager``.

Production deployments must register the provider credentials via
the secrets backend (Vault, AWS Secrets Manager, or env var) and
set the matching ``api_key`` / ``client_id`` / ``client_secret`` in
the provider config block. The sandbox endpoints are used by
default; production deployments set ``api_base_url`` to the
provider's live URL.
"""

from underwrite.services.kyc.aadhaar import AadhaarEKycClient
from underwrite.services.kyc.base import (
    Provider,
    ProviderResult,
    Verdict,
)
from underwrite.services.kyc.cibil import CibilBureauClient
from underwrite.services.kyc.ckyc import CkycSearchClient
from underwrite.services.kyc.factory import Config
from underwrite.services.kyc.pan import PanVerificationClient

__all__ = [
    "AadhaarEKycClient",
    "CibilBureauClient",
    "CkycSearchClient",
    "Provider",
    "Config",
    "PanVerificationClient",
    "ProviderResult",
    "Verdict",
]
