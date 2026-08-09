"""CIBIL consumer bureau pull — TransUnion CIBIL partner API.

The CIBIL consumer bureau pull is consumed through licensed
CIBIL partners (Perfios, Karza, CreditMantri, etc.). This client
implements the wire protocol for the standard CIBIL TUCSV1
``/v2/cibil-score`` endpoint. Partner-specific implementations
override ``_request_score``.

Wire request (POST ``/v2/cibil/score``)::

    {
      "consumer_id": "...",
      "name": "John Doe",
      "dob": "1990-01-01",
      "pan": "ABCDE1234F",
      "address": {...},
      "consent": "Y"
    }

Wire response::

    {
      "request_id": "...",
      "score": 750,
      "score_band": "Excellent",
      "tradelines": 5,
      "enquiries_last_30_days": 1,
      "defaults": []
    }
"""

from __future__ import annotations

import json

from typing import Any

from underwrite.__logger__ import logger
from underwrite.services.kyc_providers.base import KycProvider, ProviderResult, Verdict

PROVIDER_NAME = "cibil"

SANDBOX_BASE_URL = "https://uat.cibil.com"
PRODUCTION_BASE_URL = "https://api.cibil.com"

SCORE_PATH = "/v2/cibil/score"


class CibilBureauClient(KycProvider):
    """CIBIL consumer bureau pull.

    Args:
        partner_id: CIBIL partner identifier.
        partner_key: CIBIL partner API key.
        api_base_url: Endpoint base URL. Defaults to CIBIL UAT;
            production must use the live URL.
        timeout_seconds: HTTP request timeout.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        partner_id: str = "",
        partner_key: str = "",
        api_base_url: str = SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.__partner_id: str = partner_id
        self.__partner_key: str = partner_key
        self.__api_base_url: str = api_base_url.rstrip("/")
        self.__timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.__partner_id and self.__partner_key)

    def verify(
        self,
        identifier: str,
        *,
        name: str = "",
        dob: str = "",
        pan: str = "",
        address: dict[str, Any] | None = None,
        consent: str = "Y",
        **_unused: Any,
    ) -> ProviderResult:
        """Run a CIBIL consumer bureau pull.

        Args:
            identifier: CIBIL consumer id (or PAN when the partner
                supports PAN-based lookup).
            name: Holder name.
            dob: Date of birth in ``YYYY-MM-DD``.
            pan: PAN of the borrower.
            address: Address fields (street, city, state, pin).
            consent: ``"Y"`` (mandatory under DPDPA 2023).

        Returns:
            ``ProviderResult`` with ``verdict=Verdict.VERIFIED``
            and the bureau score in ``details["score"]`` on a
            successful pull.
        """
        if not consent:
            return ProviderResult(
                verdict=Verdict.REJECTED,
                provider=self.name,
                error="DPDPA consent required for CIBIL pull",
            )
        if not self.is_configured():
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error=(
                    "CIBIL client not configured; set "
                    "kyc_providers.cibil.partner_id and "
                    "kyc_providers.cibil.partner_key via the secrets "
                    "backend before calling verify()"
                ),
            )

        body: dict[str, Any] = {
            "consumer_id": identifier,
            "name": name,
            "dob": dob,
            "pan": pan,
            "address": address or {},
            "consent": consent,
        }

        try:
            response = self.request_score(body)
        except (OSError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            logger.exception("CIBIL bureau pull transport error")
            return ProviderResult(verdict=Verdict.ERROR, provider=self.name, error=str(exc))
        return self.__parse(response)

    def request_score(self, body: dict[str, Any]) -> dict[str, Any]:
        """Public transport hook so tests can inject a mock.

        Default delegates to the private __request_score. Override
        via ``client.request_score = lambda b: {...}`` to inject a
        canned response without name-mangled private access.
        """
        return self.request_score(body)

    def __request_score(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - requires httpx
            raise RuntimeError("httpx is required for CIBIL; install underwrite[serve]") from exc
        headers = {
            "Content-Type": "application/json",
            "X-Partner-ID": self.__partner_id,
            "X-Partner-Key": self.__partner_key,
        }
        with httpx.Client(timeout=self.__timeout) as client:
            response = client.post(
                f"{self.__api_base_url}{SCORE_PATH}",
                json=body,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def __parse(self, response: dict[str, Any]) -> ProviderResult:
        score = response.get("score")
        if score is None:
            return ProviderResult(
                verdict=Verdict.NOT_FOUND,
                provider=self.name,
                reference=response.get("request_id", ""),
                details=response,
                error=response.get("message", "no record returned"),
            )
        if isinstance(score, int) and 300 <= score <= 900:
            verdict = Verdict.VERIFIED
        else:
            verdict = Verdict.AMBIGUOUS
        return ProviderResult(
            verdict=verdict,
            provider=self.name,
            reference=response.get("request_id", ""),
            details={
                "score": score,
                "score_band": response.get("score_band", ""),
                "tradelines": response.get("tradelines", 0),
                "enquiries_last_30_days": response.get("enquiries_last_30_days", 0),
                "defaults": response.get("defaults", []),
            },
        )
