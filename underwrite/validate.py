"""Shared validation helpers for nano services.

All functions raise ``ProtocolError`` on invalid input, which is
silently caught by ``Core.__dispatch``, preventing state
corruption while keeping the bus alive.
"""

from __future__ import annotations

__all__ = [
    "PayloadValidator",
    "get_finite",
    "get_in_range",
    "get_match",
    "get_non_empty",
    "get_non_negative",
    "get_positive",
    "require_aadhaar",
    "require_finite",
    "require_gstin",
    "require_ifsc",
    "require_in_range",
    "require_indian_mobile",
    "require_indian_pincode",
    "require_indian_rupees",
    "require_match",
    "require_non_empty",
    "require_non_negative",
    "require_pan",
    "require_positive",
]

import math
import re
from decimal import Decimal
from typing import Any

from underwrite.__exceptions__ import ProtocolError

RE_SAFETY_UNSAFE_PATTERN: re.Pattern[str] = re.compile(r"\(\s*(?:[^()]*\[[^]]*\])*[^()]*[+*{]\s*\)\s*[+*{]}")

RE_SAFETY_MAX_PATTERN_LENGTH: int = 200

VERHOEFF_MULTIPLICATION = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

VERHOEFF_PERMUTATION = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]

VERHOEFF_INVERSE = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_checksum(digits: str) -> bool:
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = VERHOEFF_MULTIPLICATION[c][VERHOEFF_PERMUTATION[(i + 1) % 8][int(d)]]
    return VERHOEFF_INVERSE[c] == 0


class PayloadValidator:
    """Validates and extracts typed values from unstructured payload dicts.

    Each method validates a single field from a ``payload`` dict and
    returns the coerced-and-validated value.  Invalid inputs produce a
    ``ProtocolError`` that propagates up to the nano-service dispatch
    loop, which logs and discards the offending event without crashing
    the service.
    """

    @staticmethod
    def require_non_empty(value: Any, name: str) -> str:
        """Validates that *value* is a non-empty string.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The stripped string.

        Raises:
            ProtocolError: If *value* is not a non-empty string.
        """
        if not isinstance(value, str) or not value.strip():
            raise ProtocolError(f"{name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def require_finite(value: Any, name: str) -> float:
        """Validates that *value* is a finite number.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If *value* is not a finite number.
        """
        try:
            v = float(value)
        except (ValueError, TypeError) as e:
            raise ProtocolError(f"{name} must be a valid number, got {type(value).__name__}") from e
        if not math.isfinite(v):
            raise ProtocolError(f"{name} must be finite (got {v})")
        return v

    @staticmethod
    def require_positive(value: Any, name: str) -> float:
        """Validates that *value* is a positive finite number (> 0).

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If *value* is not positive.
        """
        v = PayloadValidator.require_finite(value, name)
        if v <= 0:
            raise ProtocolError(f"{name} must be positive (got {v})")
        return v

    @staticmethod
    def require_non_negative(value: Any, name: str) -> float:
        """Validates that *value* is a non-negative finite number (>= 0).

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If *value* is negative.
        """
        v = PayloadValidator.require_finite(value, name)
        if v < 0:
            raise ProtocolError(f"{name} must be non-negative (got {v})")
        return v

    @staticmethod
    def require_in_range(value: Any, lo: float, hi: float, name: str) -> float:
        """Validates that *value* is in the closed interval [*lo*, *hi*].

        Args:
            value: The value to validate.
            lo: Lower bound (inclusive).
            hi: Upper bound (inclusive).
            name: Human-readable field name for error messages.

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If *value* is outside [*lo*, *hi*].
        """
        v = PayloadValidator.require_finite(value, name)
        if not (lo <= v <= hi):
            raise ProtocolError(f"{name} must be in [{lo}, {hi}] (got {v})")
        return v

    @staticmethod
    def require_match(pattern: str, value: Any, name: str) -> str:
        """Validates that *value* matches a regex pattern.

        Guards against ReDoS by rejecting patterns with nested quantifiers
        and enforcing a maximum pattern length.

        Args:
            pattern: The regex pattern to match against.
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The matched string.

        Raises:
            ProtocolError: If *value* does not match *pattern* or the
                pattern is potentially unsafe.
        """
        s = PayloadValidator.require_non_empty(value, name)
        if len(pattern) > RE_SAFETY_MAX_PATTERN_LENGTH:
            raise ProtocolError(f"{name} pattern too long")
        if RE_SAFETY_UNSAFE_PATTERN.search(pattern):
            raise ProtocolError(f"{name} pattern rejected (nested quantifiers)")
        try:
            if not re.match(pattern, s):
                raise ProtocolError(f"{name} does not match required pattern")
        except re.error as e:
            raise ProtocolError(f"{name} pattern evaluation failed") from e
        return s

    @staticmethod
    def require_aadhaar(value: Any, name: str = "aadhaar") -> str:
        """Validates a 12-digit Aadhaar number (with Verhoeff checksum).

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The validated 12-digit Aadhaar string.

        Raises:
            ProtocolError: If the value is not a valid Aadhaar number.
        """
        s = PayloadValidator.require_non_empty(value, name)
        if not s.isdigit() or len(s) != 12:
            raise ProtocolError(f"{name} must be exactly 12 digits")
        if not verhoeff_checksum(s):
            raise ProtocolError(f"{name} failed checksum validation")
        return s

    @staticmethod
    def require_pan(value: Any, name: str = "pan") -> str:
        """Validates an Indian PAN card number.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The validated uppercase PAN string.

        Raises:
            ProtocolError: If the value is not a valid PAN.
        """
        s = PayloadValidator.require_non_empty(value, name)
        s = s.upper().strip()
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", s):
            raise ProtocolError(f"{name} must be a valid PAN (e.g. ABCDE1234F)")
        if s[3] not in "ABCEFGHJKLPT":
            raise ProtocolError(f"{name} has invalid status code (4th character)")
        return s

    @staticmethod
    def require_ifsc(value: Any, name: str = "ifsc") -> str:
        """Validates an Indian IFSC code.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The validated uppercase IFSC string.

        Raises:
            ProtocolError: If the value is not a valid IFSC code.
        """
        s = PayloadValidator.require_non_empty(value, name)
        s = s.upper().strip()
        if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", s):
            raise ProtocolError(f"{name} must be a valid IFSC code (e.g. HDFC0001234)")
        return s

    @staticmethod
    def require_indian_mobile(value: Any, name: str = "mobile") -> str:
        """Validates an Indian mobile number.

        Accepts bare 10 digits, ``+91`` prefix, or ``0`` prefix.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The normalized 10-digit mobile number.

        Raises:
            ProtocolError: If the value is not a valid Indian mobile number.
        """
        s = PayloadValidator.require_non_empty(value, name)
        s = s.strip()
        if s.startswith("+91"):
            s = s[3:]
        elif s.startswith("0"):
            s = s[1:]
        if not s.isdigit() or len(s) != 10:
            raise ProtocolError(f"{name} must be a valid 10-digit Indian mobile number")
        if s[0] not in "6789":
            raise ProtocolError(f"{name} must start with 6, 7, 8, or 9")
        return s

    @staticmethod
    def require_indian_pincode(value: Any, name: str = "pincode") -> str:
        """Validates a 6-digit Indian PIN code.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The validated 6-digit PIN code string.

        Raises:
            ProtocolError: If the value is not a valid Indian PIN code.
        """
        s = PayloadValidator.require_non_empty(value, name)
        s = s.strip()
        if not re.match(r"^[1-9][0-9]{5}$", s):
            raise ProtocolError(f"{name} must be a valid 6-digit Indian PIN code")
        return s

    @staticmethod
    def require_gstin(value: Any, name: str = "gstin") -> str:
        """Validates a 15-character Indian GSTIN.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The validated uppercase GSTIN string.

        Raises:
            ProtocolError: If the value is not a valid GSTIN.
        """
        s = PayloadValidator.require_non_empty(value, name)
        s = s.upper().strip()
        if not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", s):
            raise ProtocolError(f"{name} must be a valid 15-character GSTIN")
        return s

    @staticmethod
    def require_indian_rupees(value: Any, name: str = "amount") -> Decimal:
        """Validates an amount in Indian Rupees.

        Args:
            value: The value to validate.
            name: Human-readable field name for error messages.

        Returns:
            The amount as a ``Decimal`` with at most 2 decimal places.

        Raises:
            ProtocolError: If the value is not a valid rupee amount.
        """
        from decimal import Decimal, InvalidOperation

        try:
            v = Decimal(str(value))
        except (ValueError, TypeError, InvalidOperation) as e:
            raise ProtocolError(f"{name} must be a valid number, got {type(value).__name__}") from e
        if v < 0:
            raise ProtocolError(f"{name} must be >= 0 (got {v})")
        exp = v.as_tuple().exponent
        if isinstance(exp, int) and exp < -2:
            raise ProtocolError(f"{name} must have at most 2 decimal places")
        return v

    def non_empty(self, payload: dict[str, Any], key: str, name: str = "") -> str:
        """Returns a non-empty string from a payload dict.

        Args:
            payload: The data dictionary.
            key: The key to extract.
            name: Human-readable field name (defaults to *key*).

        Returns:
            The stripped string.

        Raises:
            ProtocolError: If the value is missing or empty.
        """
        val = payload.get(key, "")
        if isinstance(val, str):
            val = val.strip()
        return self.require_non_empty(val, name or key)

    def finite(self, payload: dict[str, Any], key: str, default: float = 0.0, name: str = "") -> float:
        """Returns a finite number from a payload dict.

        Args:
            payload: The data dictionary.
            key: The key to extract.
            default: Default if *key* is missing.
            name: Human-readable field name (defaults to *key*).

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If the value is not a finite number.
        """
        return self.require_finite(payload.get(key, default), name or key)

    def positive(self, payload: dict[str, Any], key: str, default: float = 1.0, name: str = "") -> float:
        """Returns a positive finite number from a payload dict.

        Args:
            payload: The data dictionary.
            key: The key to extract.
            default: Default if *key* is missing.
            name: Human-readable field name (defaults to *key*).

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If the value is not positive.
        """
        return self.require_positive(payload.get(key, default), name or key)

    def non_negative(self, payload: dict[str, Any], key: str, default: float = 0.0, name: str = "") -> float:
        """Returns a non-negative finite number from a payload dict.

        Args:
            payload: The data dictionary.
            key: The key to extract.
            default: Default if *key* is missing.
            name: Human-readable field name (defaults to *key*).

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If the value is negative.
        """
        return self.require_non_negative(payload.get(key, default), name or key)

    def in_range(
        self, payload: dict[str, Any], key: str, lo: float, hi: float, default: float, name: str = ""
    ) -> float:
        """Returns a value in [*lo*, *hi*] from a payload dict.

        Args:
            payload: The data dictionary.
            key: The key to extract.
            lo: Lower bound (inclusive).
            hi: Upper bound (inclusive).
            default: Default if *key* is missing.
            name: Human-readable field name (defaults to *key*).

        Returns:
            The value as a float.

        Raises:
            ProtocolError: If the value is outside [*lo*, *hi*].
        """
        return self.require_in_range(payload.get(key, default), lo, hi, name or key)

    def match(self, payload: dict[str, Any], key: str, pattern: str, name: str = "") -> str:
        """Returns a regex-matched string from a payload dict.

        Args:
            payload: The data dictionary.
            key: The key to extract.
            pattern: The regex pattern to match.
            name: Human-readable field name (defaults to *key*).

        Returns:
            The matched string.

        Raises:
            ProtocolError: If the value is missing or does not match *pattern*.
        """
        return self.require_match(pattern, payload.get(key, ""), name or key)


def require_non_empty(value: Any, name: str) -> str:
    return PayloadValidator.require_non_empty(value, name)


def require_finite(value: Any, name: str) -> float:
    return PayloadValidator.require_finite(value, name)


def require_positive(value: Any, name: str) -> float:
    return PayloadValidator.require_positive(value, name)


def require_non_negative(value: Any, name: str) -> float:
    return PayloadValidator.require_non_negative(value, name)


def require_in_range(value: Any, lo: float, hi: float, name: str) -> float:
    return PayloadValidator.require_in_range(value, lo, hi, name)


def require_match(pattern: str, value: Any, name: str) -> str:
    return PayloadValidator.require_match(pattern, value, name)


def get_non_empty(payload: dict[str, Any], key: str, name: str = "") -> str:
    return PayloadValidator().non_empty(payload, key, name)


def get_finite(payload: dict[str, Any], key: str, default: float = 0.0, name: str = "") -> float:
    return PayloadValidator().finite(payload, key, default, name)


def get_positive(payload: dict[str, Any], key: str, default: float = 1.0, name: str = "") -> float:
    return PayloadValidator().positive(payload, key, default, name)


def get_non_negative(payload: dict[str, Any], key: str, default: float = 0.0, name: str = "") -> float:
    return PayloadValidator().non_negative(payload, key, default, name)


def get_in_range(payload: dict[str, Any], key: str, lo: float, hi: float, default: float, name: str = "") -> float:
    return PayloadValidator().in_range(payload, key, lo, hi, default, name)


def get_match(payload: dict[str, Any], key: str, pattern: str, name: str = "") -> str:
    return PayloadValidator().match(payload, key, pattern, name)


def require_aadhaar(value: Any, name: str = "aadhaar") -> str:
    return PayloadValidator.require_aadhaar(value, name)


def require_pan(value: Any, name: str = "pan") -> str:
    return PayloadValidator.require_pan(value, name)


def require_ifsc(value: Any, name: str = "ifsc") -> str:
    return PayloadValidator.require_ifsc(value, name)


def require_indian_mobile(value: Any, name: str = "mobile") -> str:
    return PayloadValidator.require_indian_mobile(value, name)


def require_indian_pincode(value: Any, name: str = "pincode") -> str:
    return PayloadValidator.require_indian_pincode(value, name)


def require_gstin(value: Any, name: str = "gstin") -> str:
    return PayloadValidator.require_gstin(value, name)


def require_indian_rupees(value: Any, name: str = "amount") -> Decimal:
    return PayloadValidator.require_indian_rupees(value, name)
