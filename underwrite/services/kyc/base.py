# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Common types for KYC provider integrations."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True)
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
        """True if the verdict is a successful verification."""
        return self.verdict == Verdict.VERIFIED


class Provider:
    """Abstract KYC provider client.

    All KYC integrations implement the same surface so a deployment
    can swap one provider for another without changing the calling
    code. The base class is also the recommended hook for adding a
    mock implementation in tests — override ``_request`` to return
    a canned response.
    """

    name: str = ""

    def verify(self, identifier: str, **kwargs: Any) -> ProviderResult:  # pragma: no cover - abstract
        """Run a verification against the provider.

        Args:
            identifier: Provider-specific identifier (PAN number,
                Aadhaar token, CIBIL consumer id, CKYC number, etc.).
            **kwargs: Provider-specific extra parameters (e.g.
                Aadhaar eKYC needs demographic data, CKYC needs
                the auth factor).

        Returns:
            A standardised ``ProviderResult``. Implementations
            must never raise on provider-side errors; they must
            return ``ProviderResult(verdict=Verdict.ERROR, ...)``
            and log the underlying exception.
        """
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Returns True when the provider has the credentials it
        needs to call the real upstream API.

        Returns False for the sandbox-only default client, so
        calling code can fail fast on misconfigured production
        deployments instead of silently returning sandbox data.
        """
        return False
