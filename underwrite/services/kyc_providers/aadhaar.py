"""Aadhaar eKYC — UIDAI KUA (KYC User Agency) client.

UIDAI's eKYC service is consumed through licensed KUAs. The wire
protocol below matches the standard KUA → ASA → UIDAI request and
the encrypted response. The actual encryption layer is RSA+AES
hybrid with the KUA's public key; this client focuses on the
transport shape so deployments can plug in the KUA SDK
(``pyuid`` / ``okhota`` / proprietary) by overriding ``_send_kyc_request``.

Wire request (POST ``/eKYC/v3/auth/``)::

    {
      "aadhaar_token": "...",
      "otp": "...",
      "consent": "Y",
      "purpose": "loan-origination"
    }

Wire response (after the KUA SDK decrypts the auth response)::

    {
      "reference_id": "...",
      "status": "Y" | "N",
      "name": "John Doe",
      "dob": "1990-01-01",
      "gender": "M",
      "address": {...},
      "photo": "<base64>"
    }
"""

from __future__ import annotations

import json
from typing import Any

from underwrite.logger import logger
from underwrite.services.kyc_providers.base import Provider, ProviderResult, Verdict

PROVIDER_NAME = "aadhaar"

SANDBOX_BASE_URL = "https://stage1.uidai.gov.in"
PRODUCTION_BASE_URL = "https://www.uidai.gov.in"

E_KYC_PATH = "/eKYC/v3/auth/"


class AadhaarEKycClient(Provider):
    """Aadhaar eKYC against a UIDAI-licensed KUA.

    Args:
        kua_id: KUA identifier issued by UIDAI.
        kua_license_key: KUA license key.
        api_base_url: Endpoint base URL. Defaults to the UIDAI
            staging endpoint; production must use the live URL.
        timeout_seconds: HTTP request timeout.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        kua_id: str = "",
        kua_license_key: str = "",
        api_base_url: str = SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.__kua_id: str = kua_id
        self.__kua_license_key: str = kua_license_key
        self.__api_base_url: str = api_base_url.rstrip("/")
        self.__timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.__kua_id and self.__kua_license_key)

    def verify(
        self,
        identifier: str,
        *,
        otp: str = "",
        consent: str = "Y",
        purpose: str = "loan-origination",
        **_unused: Any,
    ) -> ProviderResult:
        """Run an eKYC authentication for a given Aadhaar.

        Args:
            identifier: Aadhaar number (12 digits) or Aadhaar
                reference token.
            otp: OTP collected from the user via the eKYC flow.
                In a real deployment this is exchanged for a
                signed Auth XML; this client carries the token
                and the encrypted payload through the KUA SDK.
            consent: ``"Y"`` (mandatory under DPDPA 2023).
            purpose: Free-text purpose code shared with the user.

        Returns:
            ``ProviderResult`` with ``verdict`` set to
            ``Verdict.VERIFIED`` on success, ``Verdict.MISMATCH``
            on a bad OTP, or ``Verdict.ERROR`` on transport /
            configuration failure.
        """
        aadhaar = (identifier or "").strip()
        if len(aadhaar) != 12 or not aadhaar.isdigit():
            return ProviderResult(
                verdict=Verdict.MISMATCH,
                provider=self.name,
                error=f"malformed Aadhaar: {identifier!r}",
            )
        if not otp:
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error="OTP is required for Aadhaar eKYC authentication",
            )
        if not consent:
            return ProviderResult(
                verdict=Verdict.REJECTED,
                provider=self.name,
                error="DPDPA consent required for Aadhaar eKYC",
            )
        if not self.is_configured():
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error=(
                    "Aadhaar eKYC client not configured; set "
                    "kyc_providers.aadhaar.kua_id and "
                    "kyc_providers.aadhaar.kua_license_key via the "
                    "secrets backend before calling verify()"
                ),
            )

        body: dict[str, Any] = {
            "aadhaar_token": aadhaar,
            "otp": otp,
            "consent": consent,
            "purpose": purpose,
        }

        try:
            response = self.send_kyc_request(body)
        except (OSError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            logger.exception("Aadhaar eKYC transport error")
            return ProviderResult(verdict=Verdict.ERROR, provider=self.name, error=str(exc))
        return self.__parse(response)

    def send_kyc_request(self, body: dict[str, Any]) -> dict[str, Any]:
        """Public transport hook so tests can inject a mock.

        Default delegates to the private __send_kyc_request. Override
        via ``client.send_kyc_request = lambda b: {...}`` to inject a
        canned response without name-mangled private access.
        """
        return self.send_kyc_request(body)

    def __send_kyc_request(self, body: dict[str, Any]) -> dict[str, Any]:
        """Submit a decrypted eKYC auth request to the KUA.

        Production deployments override this method to plug in
        the KUA SDK (``pyuid`` / ``okhota`` / vendor-specific).
        The default implementation hits the public UIDAI
        endpoint for the staging environment, which is sufficient
        for shape validation; do not use the staging endpoint
        for live verifications.
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - requires httpx
            raise RuntimeError("httpx is required for Aadhaar eKYC; install underwrite[serve]") from exc
        headers = {
            "Content-Type": "application/json",
            "X-KUA-ID": self.__kua_id,
            "X-KUA-License-Key": self.__kua_license_key,
        }
        with httpx.Client(timeout=self.__timeout) as client:
            response = client.post(
                f"{self.__api_base_url}{E_KYC_PATH}",
                json=body,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def __parse(self, response: dict[str, Any]) -> ProviderResult:
        status: str = (response.get("status") or "").upper()
        if status == "Y":
            return ProviderResult(
                verdict=Verdict.VERIFIED,
                provider=self.name,
                reference=response.get("reference_id", ""),
                details={
                    "name": response.get("name", ""),
                    "dob": response.get("dob", ""),
                    "gender": response.get("gender", ""),
                    "address": response.get("address", {}),
                    "photo_present": bool(response.get("photo")),
                },
            )
        if status == "N":
            return ProviderResult(
                verdict=Verdict.MISMATCH,
                provider=self.name,
                reference=response.get("reference_id", ""),
                error=response.get("message", "authentication failed"),
            )
        return ProviderResult(
            verdict=Verdict.ERROR,
            provider=self.name,
            reference=response.get("reference_id", ""),
            error=response.get("message", f"unexpected status {status!r}"),
        )
