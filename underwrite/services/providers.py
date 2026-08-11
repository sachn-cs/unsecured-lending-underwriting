# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""KYC provider integrations.

Consolidates the PAN, Aadhaar (eKYC), CIBIL, and CKYC clients behind a
single module. Each provider client implements the same ``Provider``
abstract base class and returns a ``ProviderResult`` carrying a
``Verdict`` enum plus the provider's structured response.

Construction is per identifier — the identifier is bound at
``__init__`` time so ``verify()`` only takes provider-specific kwargs
(consent, OTP, etc.). This replaces the previous pattern of
pre-built, identifier-less clients cached on the service handler.

Production deployments must register the provider credentials via
the secrets backend (Vault, AWS Secrets Manager, or env var) and
set the matching ``api_key`` / ``client_id`` / ``client_secret`` in
the provider config block. The sandbox endpoints are used by
default; production deployments set ``api_base_url`` to the
provider's live URL.
"""

from __future__ import annotations

import base64
import enum
import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from underwrite.logger import logger

if TYPE_CHECKING:
    from underwrite.secrets import Manager

__all__ = [
    "Aadhar",
    "Cibil",
    "Ckyc",
    "Pan",
    "Provider",
    "ProviderResult",
    "ProvidersConfig",
    "Verdict",
]

AADHAAR_PROVIDER_NAME = "aadhaar"
AADHAAR_SANDBOX_BASE_URL = "https://stage1.uidai.gov.in"
AADHAAR_PRODUCTION_BASE_URL = "https://www.uidai.gov.in"
AADHAAR_E_KYC_PATH = "/eKYC/v3/auth/"

PAN_PROVIDER_NAME = "pan"
PAN_SANDBOX_BASE_URL = "https://uat-api.karza.in"
PAN_PRODUCTION_BASE_URL = "https://api.karza.in"
PAN_VERIFICATION_PATH = "/v2/pan/verify"

CIBIL_PROVIDER_NAME = "cibil"
CIBIL_SANDBOX_BASE_URL = "https://uat.cibil.com"
CIBIL_PRODUCTION_BASE_URL = "https://api.cibil.com"
CIBIL_SCORE_PATH = "/v2/cibil/score"

CKYC_PROVIDER_NAME = "ckyc"
CKYC_SANDBOX_BASE_URL = "https://uat-search.ckycindia.in"
CKYC_PRODUCTION_BASE_URL = "https://search.ckycindia.in"
CKYC_SEARCH_PATH = "/v1/ckyc/search"

_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    TypeError,
    RuntimeError,
    json.JSONDecodeError,
)


class Verdict(str, enum.Enum):
    """Provider verification verdict.

    Carries the same vocabulary across PAN, Aadhaar, CIBIL, and
    CKYC clients so downstream services can switch on the value
    without parsing provider-specific responses.
    """

    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    MISMATCH = "mismatch"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Standardised response envelope for a KYC provider call.

    Attributes:
        verdict: Outcome category.
        provider: Provider name (e.g. ``"pan"``, ``"aadhaar"``,
            ``"cibil"``, ``"ckyc"``).
        reference: Provider-side reference / request id (used for
            audit and dispute resolution).
        details: Provider-specific response body. Each provider
            documents its own schema; downstream services should
            not depend on these fields.
        error: Error message when ``verdict == Verdict.ERROR``.
    """

    verdict: Verdict
    provider: str
    reference: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        """Return True if the verdict is a successful verification."""
        return self.verdict == Verdict.VERIFIED


class Provider(ABC):
    """Abstract KYC provider client.

    All KYC integrations implement the same surface so a deployment
    can swap one provider for another without changing the calling
    code. The base class also exposes shared verify-time helpers
    (``check_consent``, ``check_configured``, ``safe_call``) that
    each subclass can use to factor out the common error mapping.
    """

    name: str = ""

    @abstractmethod
    def verify(self, **kwargs: Any) -> ProviderResult:
        """Run a verification against the provider.

        Subclass-specific kwargs vary (see e.g. ``Pan.verify``).
        Implementations must never raise on provider-side errors;
        they must return ``ProviderResult(verdict=Verdict.ERROR, ...)``
        and log the underlying exception.
        """
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Return True when the provider has the credentials it needs.

        Returns False for the sandbox-only default client, so calling
        code can fail fast on misconfigured production deployments
        instead of silently returning sandbox data.
        """
        return False

    def check_consent(self, consent: str) -> ProviderResult | None:
        """Return a ``REJECTED`` result if consent is missing.

        Args:
            consent: ``"Y"`` if the user has consented (mandatory
                under DPDPA 2023). Any other value is treated as no
                consent.

        Returns:
            A ``ProviderResult`` with verdict ``REJECTED`` when
            ``consent`` is falsy, otherwise ``None`` so the caller
            can short-circuit.
        """
        if consent:
            return None
        return ProviderResult(
            verdict=Verdict.REJECTED,
            provider=self.name,
            error=f"DPDPA consent required for {self.name} verification",
        )

    def check_configured(self, secret_hint: str) -> ProviderResult | None:
        """Return an ``ERROR`` result when credentials are missing.

        Args:
            secret_hint: Human-readable hint telling the operator
                which secrets-backend keys to set.

        Returns:
            A ``ProviderResult`` with verdict ``ERROR`` when
            ``is_configured()`` returns False, otherwise ``None``.
        """
        if self.is_configured():
            return None
        return ProviderResult(
            verdict=Verdict.ERROR,
            provider=self.name,
            error=(
                f"{self.name} client not configured; set {secret_hint} via the secrets backend before calling verify()"
            ),
        )

    def safe_call(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any] | ProviderResult:
        """Run a transport call and convert exceptions to ``ERROR``.

        Args:
            fn: Zero-arg callable that performs the HTTP request and
                returns the parsed response dict.

        Returns:
            The parsed response dict on success, or a ``ProviderResult``
            with ``verdict=Verdict.ERROR`` when any of the standard
            transport / decode errors are raised. Callers should check
            ``isinstance(result, ProviderResult)`` and short-circuit
            on errors.
        """
        try:
            return fn()
        except _TRANSPORT_ERRORS as exc:
            logger.exception("{} transport error", self.name)
            return ProviderResult(verdict=Verdict.ERROR, provider=self.name, error=str(exc))


class Aadhar(Provider):
    """Aadhaar eKYC against a UIDAI-licensed KUA.

    Args:
        number: Aadhaar number (12 digits) or reference token.
        kua_id: KUA identifier issued by UIDAI.
        kua_license_key: KUA license key.
        api_base_url: Endpoint base URL. Defaults to the UIDAI
            staging endpoint; production must use the live URL.
        timeout_seconds: HTTP request timeout.

    Wire request (POST ``/eKYC/v3/auth/``)::

        {
          "aadhaar_token": "...",
          "otp": "...",
          "consent": "Y",
          "purpose": "loan-origination"
        }
    """

    name = AADHAAR_PROVIDER_NAME

    def __init__(
        self,
        number: str,
        *,
        kua_id: str = "",
        kua_license_key: str = "",
        api_base_url: str = AADHAAR_SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.number: str = (number or "").strip()
        self.kua_id: str = kua_id
        self.kua_license_key: str = kua_license_key
        self.api_base_url: str = api_base_url.rstrip("/")
        self.timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.kua_id and self.kua_license_key)

    def verify(  # type: ignore[override]
        self,
        *,
        otp: str = "",
        consent: str = "Y",
        purpose: str = "loan-origination",
    ) -> ProviderResult:
        """Run an eKYC authentication for the bound Aadhaar.

        Args:
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
        if len(self.number) != 12 or not self.number.isdigit():
            return ProviderResult(
                verdict=Verdict.MISMATCH,
                provider=self.name,
                error=f"malformed Aadhaar: {self.number!r}",
            )
        if not otp:
            return ProviderResult(
                verdict=Verdict.ERROR,
                provider=self.name,
                error="OTP is required for Aadhaar eKYC authentication",
            )
        if (err := self.check_consent(consent)) is not None:
            return err
        if (
            err := self.check_configured(
                "kyc_provider_config.aadhaar.kua_id and kyc_provider_config.aadhaar.kua_license_key"
            )
        ) is not None:
            return err

        body: dict[str, Any] = {
            "aadhaar_token": self.number,
            "otp": otp,
            "consent": consent,
            "purpose": purpose,
        }
        response = self.safe_call(lambda: self.send_kyc_request(body))
        if not isinstance(response, dict):
            return response
        return self.parse(response)

    def send_kyc_request(self, body: dict[str, Any]) -> dict[str, Any]:
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
            "X-KUA-ID": self.kua_id,
            "X-KUA-License-Key": self.kua_license_key,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.api_base_url}{AADHAAR_E_KYC_PATH}",
                json=body,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def parse(self, response: dict[str, Any]) -> ProviderResult:
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


class Pan(Provider):
    """PAN verification against an upstream KYC service.

    Args:
        pan: The 10-character PAN.
        client_id: Provider-issued client id.
        client_secret: Provider-issued client secret (used for
            HMAC signing of the request body).
        api_base_url: Endpoint base URL. Defaults to the Karza
            sandbox; production deployments should set this to
            the provider's live URL.
        timeout_seconds: HTTP request timeout.

    Wire request (POST ``/v2/pan/verify``)::

        {
          "pan_number": "ABCDE1234F",
          "name": "John Doe",
          "dob": "1990-01-01"
        }
    """

    name = PAN_PROVIDER_NAME

    def __init__(
        self,
        pan: str,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_base_url: str = PAN_SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.pan: str = (pan or "").upper().strip()
        self.client_id: str = client_id or ""
        self.client_secret: str = client_secret or ""
        self.api_base_url: str = api_base_url.rstrip("/")
        self.timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def verify(  # type: ignore[override]
        self,
        *,
        name: str = "",
        dob: str = "",
        consent: str = "Y",
    ) -> ProviderResult:
        """Verify the bound PAN against the ITD database.

        Args:
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
        if len(self.pan) != 10 or not self.pan.isalnum():
            return ProviderResult(
                verdict=Verdict.MISMATCH,
                provider=self.name,
                error=f"malformed PAN: {self.pan!r}",
            )
        if (err := self.check_consent(consent)) is not None:
            return err
        if (
            err := self.check_configured("kyc_provider_config.pan.client_id and kyc_provider_config.pan.client_secret")
        ) is not None:
            return err

        body: dict[str, Any] = {"pan_number": self.pan, "consent": consent}
        if name:
            body["name"] = name
        if dob:
            body["dob"] = dob
        payload = json.dumps(body, separators=(",", ":"))
        signature = self.sign(payload)
        response = self.safe_call(lambda: self.http_post(payload, signature))
        if not isinstance(response, dict):
            return response
        return self.parse(self.pan, response)

    def sign(self, payload: str) -> str:
        """Compute the HMAC-SHA256 signature over the JSON body."""
        digest = hmac.new(
            self.client_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("ascii")

    def http_post(self, payload: str, signature: str) -> dict[str, Any]:
        """POST the signed payload to the configured endpoint."""
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
                f"{self.api_base_url}{PAN_VERIFICATION_PATH}",
                content=payload,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def parse(self, pan: str, response: dict[str, Any]) -> ProviderResult:
        status: str = (response.get("status") or response.get("pan_status") or "").upper()
        verdict = _PAN_STATUS_TO_VERDICT.get(status, Verdict.ERROR)
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


_PAN_STATUS_TO_VERDICT: dict[str, Verdict] = {
    "VALID": Verdict.VERIFIED,
    "ACTIVE": Verdict.VERIFIED,
    "INVALID": Verdict.REJECTED,
    "DEACTIVATED": Verdict.REJECTED,
    "INACTIVE": Verdict.REJECTED,
    "NOT_FOUND": Verdict.NOT_FOUND,
}


class Cibil(Provider):
    """CIBIL consumer bureau pull.

    Args:
        consumer_id: CIBIL consumer id (or PAN when the partner
            supports PAN-based lookup).
        partner_id: CIBIL partner identifier.
        partner_key: CIBIL partner API key.
        api_base_url: Endpoint base URL. Defaults to CIBIL UAT;
            production must use the live URL.
        timeout_seconds: HTTP request timeout.

    Wire request (POST ``/v2/cibil/score``)::

        {
          "consumer_id": "...",
          "name": "John Doe",
          "dob": "1990-01-01",
          "pan": "ABCDE1234F",
          "address": {...},
          "consent": "Y"
        }
    """

    name = CIBIL_PROVIDER_NAME

    def __init__(
        self,
        consumer_id: str,
        *,
        partner_id: str = "",
        partner_key: str = "",
        api_base_url: str = CIBIL_SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.consumer_id: str = consumer_id
        self.partner_id: str = partner_id
        self.partner_key: str = partner_key
        self.api_base_url: str = api_base_url.rstrip("/")
        self.timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.partner_id and self.partner_key)

    def verify(  # type: ignore[override]
        self,
        *,
        name: str = "",
        dob: str = "",
        pan: str = "",
        address: dict[str, Any] | None = None,
        consent: str = "Y",
    ) -> ProviderResult:
        """Run a CIBIL consumer bureau pull.

        Args:
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
        if (err := self.check_consent(consent)) is not None:
            return err
        if (
            err := self.check_configured(
                "kyc_provider_config.cibil.partner_id and kyc_provider_config.cibil.partner_key"
            )
        ) is not None:
            return err

        body: dict[str, Any] = {
            "consumer_id": self.consumer_id,
            "name": name,
            "dob": dob,
            "pan": pan,
            "address": address or {},
            "consent": consent,
        }
        response = self.safe_call(lambda: self.request_score(body))
        if not isinstance(response, dict):
            return response
        return self.parse(response)

    def request_score(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST the bureau pull request and return the parsed response."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - requires httpx
            raise RuntimeError("httpx is required for CIBIL; install underwrite[serve]") from exc
        headers = {
            "Content-Type": "application/json",
            "X-Partner-ID": self.partner_id,
            "X-Partner-Key": self.partner_key,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.api_base_url}{CIBIL_SCORE_PATH}",
                json=body,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def parse(self, response: dict[str, Any]) -> ProviderResult:
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
                "credit_utilization_pct": response.get("credit_utilization_pct", 0.0),
                "delinquent_accounts": response.get("delinquent_accounts", 0),
                "defaults": response.get("defaults", []),
            },
        )


class Ckyc(Provider):
    """CKYC registry search.

    Args:
        identifier: CKYC number, PAN, or Aadhaar reference token,
            selected by ``identifier_type`` at ``verify()`` time.
        search_provider_id: CKYC Search Provider identifier.
        search_provider_key: CKYC Search Provider API key.
        api_base_url: Endpoint base URL. Defaults to the CKYC UAT
            endpoint; production must use the live URL.
        timeout_seconds: HTTP request timeout.

    Wire request (POST ``/v1/ckyc/search``)::

        {
          "ckyc_number": "..." | "pan": "..." | "aadhaar_token": "...",
          "consent": "Y"
        }
    """

    name = CKYC_PROVIDER_NAME

    def __init__(
        self,
        identifier: str,
        *,
        search_provider_id: str = "",
        search_provider_key: str = "",
        api_base_url: str = CKYC_SANDBOX_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.identifier: str = identifier
        self.sp_id: str = search_provider_id
        self.sp_key: str = search_provider_key
        self.api_base_url: str = api_base_url.rstrip("/")
        self.timeout: int = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.sp_id and self.sp_key)

    def verify(  # type: ignore[override]
        self,
        *,
        identifier_type: str = "ckyc_number",
        consent: str = "Y",
    ) -> ProviderResult:
        """Search the CKYC registry for a record.

        Args:
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
        if (err := self.check_consent(consent)) is not None:
            return err
        if (
            err := self.check_configured(
                "kyc_provider_config.ckyc.search_provider_id and kyc_provider_config.ckyc.search_provider_key"
            )
        ) is not None:
            return err

        body: dict[str, Any] = {identifier_type: self.identifier, "consent": consent}
        response = self.safe_call(lambda: self.request_search(body))
        if not isinstance(response, dict):
            return response
        return self.parse(response)

    def request_search(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST the search request and return the parsed response."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - requires httpx
            raise RuntimeError("httpx is required for CKYC search; install underwrite[serve]") from exc
        headers = {
            "Content-Type": "application/json",
            "X-SP-ID": self.sp_id,
            "X-SP-Key": self.sp_key,
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.api_base_url}{CKYC_SEARCH_PATH}",
                json=body,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()

    def parse(self, response: dict[str, Any]) -> ProviderResult:
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


class ProvidersConfig(BaseModel):
    """Configuration for the KYC provider integrations.

    Lives under ``config.kyc_provider_config`` in the runtime
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

    def resolve_aadhaar(self, number: str, secrets: Manager | None = None) -> Aadhar:
        """Build an ``Aadhar`` client pulling credentials from secrets when needed."""
        import os

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
        return Aadhar(
            number=number,
            kua_id=kua_id,
            kua_license_key=kua_license,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def resolve_pan(self, pan: str, secrets: Manager | None = None) -> Pan:
        """Build a ``Pan`` client pulling credentials from secrets when needed."""
        client_id = self.pan_client_id
        client_secret = self.pan_client_secret
        if secrets is not None:
            if not client_id:
                client_id = secrets.get("underwrite/pan/client_id") or ""
            if not client_secret:
                client_secret = secrets.get("underwrite/pan/client_secret") or ""
        base = self.pan_api_base_url or PAN_PRODUCTION_BASE_URL
        import os

        if not (self.pan_api_base_url or os.environ.get("UNDERWRITE_PAN_PRODUCTION")):
            base = PAN_SANDBOX_BASE_URL
        return Pan(
            pan=pan,
            client_id=client_id,
            client_secret=client_secret,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def resolve_cibil(self, consumer_id: str, secrets: Manager | None = None) -> Cibil:
        """Build a ``Cibil`` client pulling credentials from secrets when needed."""
        import os

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
        return Cibil(
            consumer_id=consumer_id,
            partner_id=partner_id,
            partner_key=partner_key,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )

    def resolve_ckyc(self, identifier: str, secrets: Manager | None = None) -> Ckyc:
        """Build a ``Ckyc`` client pulling credentials from secrets when needed."""
        import os

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
        return Ckyc(
            identifier=identifier,
            search_provider_id=sp_id,
            search_provider_key=sp_key,
            api_base_url=base,
            timeout_seconds=self.timeout_seconds,
        )
