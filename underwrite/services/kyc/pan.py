# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""PAN verification — Income Tax Department (NSDL / UTIITSL).

The Income Tax Department exposes PAN verification through licensed
KYC service providers (Karza, Signzy, Onfido, etc.). This client
implements the wire protocol for the Karza-style ``/v2/pan/verify``
endpoint and falls back to a sandbox URL when no production
credentials are configured.

The endpoint is HMAC-signed. The ``client_id`` and ``client_secret``
are issued by the KYC provider on registration. The same shape
works for Signzy with a different ``api_base_url``.

Wire request (POST ``/v2/pan/verify``)::

    {
      "pan_number": "ABCDE1234F",
      "name": "John Doe",
      "dob": "1990-01-01"  // optional
    }

Wire response::

    {
      "request_id": "...",
      "status": "VALID" | "INVALID" | "DEACTIVATED",
      "pan_status": "ACTIVE" | "INACTIVE",
      "pan_type": "Individual",
      "first_name": "John",
      "last_name": "Doe",
      "aadhaar_seeding_status": "Y" | "N"
    }
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from underwrite.logger import logger
from underwrite.services.kyc.base import Provider, ProviderResult, Verdict

PROVIDER_NAME = "pan"

SANDBOX_BASE_URL = "https://uat-api.karza.in"
PRODUCTION_BASE_URL = "https://api.karza.in"

VERIFICATION_PATH = "/v2/pan/verify"


_STATUS_TO_VERDICT: dict[str, Verdict] = {
    "VALID": Verdict.VERIFIED,
    "ACTIVE": Verdict.VERIFIED,
    "INVALID": Verdict.REJECTED,
    "DEACTIVATED": Verdict.REJECTED,
    "INACTIVE": Verdict.REJECTED,
    "NOT_FOUND": Verdict.NOT_FOUND,
}


class PanVerificationClient(Provider):
    """PAN verification against an upstream KYC service.

    Args:
        client_id: Provider-issued client id.
        client_secret: Provider-issued client secret (used for
            HMAC signing of the request body).
        api_base_url: Endpoint base URL. Defaults to the Karza
            sandbox; production deployments should set this to
            the provider's live URL.
        timeout_seconds: HTTP request timeout.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_base_url: str = SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.client_id: str = client_id or ""
        self.client_secret: str = client_secret or ""
        self.api_base_url: str = api_base_url.rstrip("/")
        self.timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def verify(
        self,
        identifier: str,
        *,
        name: str = "",
        dob: str = "",
        consent: str = "Y",
        **_unused: Any,
    ) -> ProviderResult:
        """Verify a PAN against the ITD database.

        Args:
            identifier: The 10-character PAN.
            name: Holder name (optional, increases match confidence).
            dob: Date of birth in ``YYYY-MM-DD`` (optional).
            consent: ``"Y"`` if the user has consented to the
                verification (mandatory under DPDPA 2023).

        Returns:
            A ``ProviderResult`` whose ``verdict`` is one of
            ``Verdict.VERIFIED`` (PAN is valid and active),
            ``Verdict.NOT_FOUND`` (no record), ``Verdict.REJECTED``
            (deactivated / invalid), or ``Verdict.ERROR`` (transport
            or upstream failure).
        """
        pan = (identifier or "").upper().strip()
        if len(pan) != 10 or not pan.isalnum():
            return ProviderResult(
                verdict=Verdict.MISMATCH,
                provider=self.name,
                error=f"malformed PAN: {identifier!r}",
            )
        if not consent:
            return ProviderResult(
                verdict=Verdict.REJECTED,
                provider=self.name,
                error="DPDPA consent required for PAN verification",
            )

        if not self.is_configured():
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error=(
                    "PAN verification client not configured; set "
                    "kyc_providers.pan.client_id and "
                    "kyc_providers.pan.client_secret via the secrets "
                    "backend before calling verify()"
                ),
            )

        body: dict[str, Any] = {"pan_number": pan, "consent": consent}
        if name:
            body["name"] = name
        if dob:
            body["dob"] = dob
        payload = json.dumps(body, separators=(",", ":"))
        signature = self.sign(payload)

        try:
            response = self.http_post(payload, signature)
        except (OSError, ValueError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            logger.exception("PAN verification transport error")
            return ProviderResult(verdict=Verdict.ERROR, provider=self.name, error=str(exc))

        return self.parse(pan, response)

    def sign(self, payload: str) -> str:
        digest = hmac.new(
            self.client_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("ascii")

    def http_post(self, payload: str, signature: str) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - requires httpx
            raise RuntimeError("httpx is required for PAN verification; install underwrite[serve]") from exc
        headers = {
            "Content-Type": "application/json",
            "x-client-id": self.client_id,
            "x-signature": signature,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.api_base_url}{VERIFICATION_PATH}",
                content=payload,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def parse(self, pan: str, response: dict[str, Any]) -> ProviderResult:
        status: str = (response.get("status") or response.get("pan_status") or "").upper()
        verdict = _STATUS_TO_VERDICT.get(status, Verdict.ERROR)
        return ProviderResult(
            verdict=verdict,
            provider=self.name,
            reference=response.get("request_id", ""),
            details={
                "pan": pan,
                "pan_status": response.get("pan_status", ""),
                "pan_type": response.get("pan_type", ""),
                "first_name": response.get("first_name", ""),
                "last_name": response.get("last_name", ""),
                "aadhaar_seeding_status": response.get("aadhaar_seeding_status", ""),
            },
            error=response.get("message", "") if verdict == Verdict.ERROR else "",
        )
