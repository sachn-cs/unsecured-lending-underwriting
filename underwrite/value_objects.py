# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Domain value objects.

AGENTS.md § Primitive Obsession: domain concepts should be modeled
as named value objects rather than raw ``str`` / ``float`` / ``int``
primitives. This module introduces:

- ``Money`` — amount in paise (integer, smallest unit) plus currency.
- ``Rate`` — annual interest rate as a finite Decimal (e.g. 0.18 for 18%).
- ``UserId`` / ``LoanId`` / ``ApplicationId`` — opaque identifier
  newtypes backed by ``str``.

These are intentionally minimal: each captures the one invariant
that is most commonly violated when the underlying primitive is
used (currency mixing, negative principal, empty/whitespace id).
Adoption is incremental; new code should use these types in
signatures and store APIs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import NewType

from underwrite.exceptions import ProtocolError

__all__ = [
    "ApplicationId",
    "LoanId",
    "Money",
    "Rate",
    "UserId",
    "paise_to_rupees",
    "rupees_to_paise",
]

PAISE_PER_RUPEE: int = 100


def paise_to_rupees(paise: int) -> Decimal:
    """Convert paise (smallest currency unit) to rupees as Decimal."""
    return Decimal(paise) / Decimal(PAISE_PER_RUPEE)


def rupees_to_paise(rupees: Decimal | float | str) -> int:
    """Convert rupees to paise (smallest currency unit) as int.

    Rounds half-up to the nearest paise. Raises ProtocolError if the
    input is not finite.
    """
    try:
        amount = Decimal(str(rupees))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProtocolError(f"rupees must be a finite number, got {rupees!r}") from exc
    if not amount.is_finite():
        raise ProtocolError(f"rupees must be finite, got {rupees!r}")
    return int((amount * PAISE_PER_RUPEE).quantize(Decimal("1")))


@dataclass(frozen=True, slots=True)
class Money:
    """A monetary amount in paise plus an ISO-4217 currency code.

    Paise (the smallest currency unit) is an integer, so addition
    and comparison are exact. Construct via ``rupees_to_paise`` or
    the ``from_rupees`` helper; never pass a ``float`` directly.
    """

    paise: int
    currency: str = "INR"

    def __post_init__(self) -> None:
        if self.paise < 0:
            raise ProtocolError(f"Money.paise must be >= 0, got {self.paise}")
        if not self.currency or not self.currency.isalpha():
            raise ProtocolError(f"Money.currency must be a non-empty alpha code, got {self.currency!r}")

    @classmethod
    def from_rupees(cls, rupees: Decimal | float | str, currency: str = "INR") -> Money:
        return cls(paise=rupees_to_paise(rupees), currency=currency)

    @property
    def rupees(self) -> Decimal:
        return paise_to_rupees(self.paise)

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ProtocolError(f"cannot add Money in {self.currency} and {other.currency}")
        return Money(paise=self.paise + other.paise, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ProtocolError(f"cannot subtract Money in {self.currency} and {other.currency}")
        if self.paise < other.paise:
            raise ProtocolError(f"negative Money result: {self.paise} - {other.paise}")
        return Money(paise=self.paise - other.paise, currency=self.currency)


@dataclass(frozen=True, slots=True)
class Rate:
    """An annual interest rate as a finite Decimal between 0.0 and 1.0.

    0.18 represents 18% per annum. Construct via ``Rate(Decimal(\"0.18\"))``
    — the constructor refuses negative, NaN, or out-of-range values
    so the invariant is enforced at the type boundary.
    """

    annual: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.annual, Decimal):
            raise ProtocolError(f"Rate.annual must be a Decimal, got {type(self.annual).__name__}")
        if not self.annual.is_finite():
            raise ProtocolError(f"Rate.annual must be finite, got {self.annual}")
        if self.annual < Decimal("0"):
            raise ProtocolError(f"Rate.annual must be >= 0, got {self.annual}")

    @classmethod
    def from_fraction(cls, fraction: float | int | str, *, max_fraction: Decimal = Decimal("5")) -> Rate:
        """Parse a decimal fraction (e.g. 0.18) with an upper bound default.

        The default ``max_fraction=5`` allows up to 500% annual rate
        to accommodate regulatory edge cases; tighten in domain code.
        """
        try:
            value = Decimal(str(fraction))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ProtocolError(f"Rate.from_fraction requires a number, got {fraction!r}") from exc
        if not value.is_finite():
            raise ProtocolError(f"Rate must be finite, got {fraction}")
        if value < 0 or value > max_fraction:
            raise ProtocolError(f"Rate {value} out of range [0, {max_fraction}]")
        return cls(annual=value)

    @property
    def monthly(self) -> Decimal:
        return self.annual / Decimal("12")

    @property
    def daily_365(self) -> Decimal:
        return self.annual / Decimal("365")


_NON_EMPTY_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def _validate_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError("id must be a non-empty string")
    if not _NON_EMPTY_ID.match(value):
        raise ProtocolError(f"id must match {_NON_EMPTY_ID.pattern}, got {value!r}")
    return value


class IdGenerator:
    """Domain ID generator with deterministic test override.

    Production callers use the default UUID4-backed implementation.
    Tests inject a counter-backed implementation to make IDs
    reproducible without coupling tests to UUID randomness.
    """

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.counter = 0

    def next(self) -> str:
        """Return a new unique random hex identifier (12 chars)."""
        import uuid as _uuid

        return _uuid.uuid4().hex[:12]

    def deterministic_next(self) -> str:
        """Return a deterministic counter-backed identifier.

        Used exclusively by tests for reproducibility; falls back
        to ``next()`` if the counter would overflow.
        """
        self.counter += 1
        return f"{self.counter:08d}"


UserId = NewType("UserId", str)
LoanId = NewType("LoanId", str)
ApplicationId = NewType("ApplicationId", str)


def user_id(value: str) -> UserId:
    return UserId(_validate_id(value))


def loan_id(value: str) -> LoanId:
    return LoanId(_validate_id(value))


def application_id(value: str) -> ApplicationId:
    return ApplicationId(_validate_id(value))
