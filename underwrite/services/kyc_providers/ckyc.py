"""CKYC registry search — CERSAI (Central KYC Records Registry).

CKYC lookup is consumed through licensed CKYC Search Providers
(Karza, IDfy, etc.). This client implements the wire protocol for
the standard ``/v1/ckyc/search`` endpoint.

Wire request (POST ``/v1/ckyc/search``)::

    {
      "ckyc_number": "..." | "pan": "..." | "aadhaar_token": "...",
      "consent": "Y"
    }

Wire response::

    {
      "request_id": "...",
      "ckyc_number": "...",
      "name": "John Doe",
      "dob": "1990-01-01",
      "pan": "ABCDE1234F",
      "aadhaar_last4": "1234",
      "address": {...},
      "image_present": true,
      "kyc_status": "VERIFIED"
    }
"""

from __future__ import annotations

import json

from typing import Any

from underwrite.__logger__ import logger
from underwrite.services.kyc_providers.base import KycProvider, ProviderResult, Verdict

PROVIDER_NAME = "ckyc"

SANDBOX_BASE_URL = "https://uat-search.ckycindia.in"
PRODUCTION_BASE_URL = "https://search.ckycindia.in"

SEARCH_PATH = "/v1/ckyc/search"


class CkycSearchClient(KycProvider):
    """CKYC registry search.

    Args:
        search_provider_id: CKYC Search Provider identifier.
        search_provider_key: CKYC Search Provider API key.
        api_base_url: Endpoint base URL. Defaults to the CKYC UAT
            endpoint; production must use the live URL.
        timeout_seconds: HTTP request timeout.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        search_provider_id: str = "",
        search_provider_key: str = "",
        api_base_url: str = SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.__sp_id: str = search_provider_id
        self.__sp_key: str = search_provider_key
        self.__api_base_url: str = api_base_url.rstrip("/")
        self.__timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.__sp_id and self.__sp_key)

    def verify(
        self,
        identifier: str,
        *,
        identifier_type: str = "ckyc_number",
        consent: str = "Y",
        **_unused: Any,
    ) -> ProviderResult:
        """Search the CKYC registry for a record.

        Args:
            identifier: The CKYC number, PAN, or Aadhaar reference
                token (depending on ``identifier_type``).
            identifier_type: One of ``"ckyc_number"``, ``"pan"``,
                ``"aadhaar"``.
            consent: ``"Y"`` (mandatory under DPDPA 2023).

        Returns:
            ``ProviderResult`` with ``verdict=Verdict.VERIFIED``
            and the KYC details in ``details`` on a hit,
            ``Verdict.NOT_FOUND`` on a miss, ``Verdict.ERROR`` on
            transport or configuration failure.
        """
        if identifier_type not in ("ckyc_number", "pan", "aadhaar"):
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error=f"unsupported identifier_type: {identifier_type!r}",
            )
        if not consent:
            return ProviderResult(
                verdict=Verdict.REJECTED,
                provider=self.name,
                error="DPDPA consent required for CKYC search",
            )
        if not self.is_configured():
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error=(
                    "CKYC search client not configured; set "
                    "kyc_providers.ckyc.search_provider_id and "
                    "kyc_providers.ckyc.search_provider_key via the "
                    "secrets backend before calling verify()"
                ),
            )

        body: dict[str, Any] = {identifier_type: identifier, "consent": consent}

        try:
            response = self.request_search(body)
        except (OSError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            logger.exception("CKYC search transport error")
            return ProviderResult(verdict=Verdict.ERROR, provider=self.name, error=str(exc))
        return self.__parse(response)

    def request_search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Public transport hook so tests can inject a mock.

        Default delegates to the private __request_search. Override
        via ``client.request_search = lambda b: {...}`` to inject a
        canned response without name-mangled private access.
        """
        return self.request_search(body)

    def __request_search(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - requires httpx
            raise RuntimeError("httpx is required for CKYC search; install underwrite[serve]") from exc
        headers = {
            "Content-Type": "application/json",
            "X-SP-ID": self.__sp_id,
            "X-SP-Key": self.__sp_key,
        }
        with httpx.Client(timeout=self.__timeout) as client:
            response = client.post(
                f"{self.__api_base_url}{SEARCH_PATH}",
                json=body,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def __parse(self, response: dict[str, Any]) -> ProviderResult:
        if response.get("kyc_status") == "VERIFIED" or response.get("ckyc_number"):
            return ProviderResult(
                verdict=Verdict.VERIFIED,
                provider=self.name,
                reference=response.get("request_id", ""),
                details={
                    "ckyc_number": response.get("ckyc_number", ""),
                    "name": response.get("name", ""),
                    "dob": response.get("dob", ""),
                    "pan": response.get("pan", ""),
                    "aadhaar_last4": response.get("aadhaar_last4", ""),
                    "address": response.get("address", {}),
                    "image_present": bool(response.get("image_present", False)),
                },
            )
        if response.get("kyc_status") == "NOT_FOUND" or response.get("status") == "not_found":
            return ProviderResult(
                verdict=Verdict.NOT_FOUND,
                provider=self.name,
                reference=response.get("request_id", ""),
                details=response,
            )
        return ProviderResult(
            verdict=Verdict.ERROR,
            provider=self.name,
            reference=response.get("request_id", ""),
            details=response,
            error=response.get("message", "unexpected CKYC response"),
        )
