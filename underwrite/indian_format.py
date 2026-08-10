"""Indian number formatting utilities.

Provides lakh/crore-based formatting for display of monetary amounts
in Indian locale conventions.

Examples:
  ₹1,23,456.78  (1 lakh 23 thousand 456 rupees 78 paise)
  ₹12,34,56,789.00  (12 crore 34 lakh 56 thousand 789 rupees)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _to_decimal(value: float | str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def format_indian_rupees(value: float | str | Decimal) -> str:
    """Format a monetary amount in Indian rupee style (lakh/crore).

    Uses the Indian numbering system where grouping is:
      1st group: 3 digits (hundreds)
      Subsequent groups: 2 digits each (thousands, lakhs, crores)

    Args:
        value: Numeric amount to format.

    Returns:
        Formatted string like "₹1,23,456.78" or "₹0.00".

    Raises:
        ValueError: If the value is non-finite.
    """
    d = _to_decimal(value)
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d < 0:
        return "-" + format_indian_rupees(-d)
    parts = str(d).split(".")
    integer_part = parts[0]
    decimal_part = parts[1] if len(parts) > 1 else "00"
    if len(decimal_part) < 2:
        decimal_part = decimal_part.ljust(2, "0")
    elif len(decimal_part) > 2:
        decimal_part = decimal_part[:2]

    last_three = integer_part[-3:] if len(integer_part) > 3 else integer_part
    rest = integer_part[:-3] if len(integer_part) > 3 else ""
    groups: list[str] = [last_three]
    while rest:
        groups.insert(0, rest[-2:] if len(rest) >= 2 else rest)
        rest = rest[:-2] if len(rest) >= 2 else ""
    return "₹" + ",".join(groups) + "." + decimal_part


def format_indian_words(value: float | str | Decimal, include_paise: bool = True) -> str:
    """Convert a monetary amount to Indian English words.

    Args:
        value: Numeric amount.
        include_paise: Whether to include paise in output.

    Returns:
        String like "Twelve Crore Thirty Four Lakh Fifty Six
        Thousand Seven Hundred Eighty Nine Rupees and Fifty Paise".
    """
    d = _to_decimal(value)
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d < 0:
        return "Negative " + format_indian_words(-d, include_paise)
    integer_part = int(d)
    paise = int((d - Decimal(integer_part)) * Decimal("100"))

    if integer_part == 0 and paise == 0:
        return "Zero Rupees"

    ones = [
        "",
        "One",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Eleven",
        "Twelve",
        "Thirteen",
        "Fourteen",
        "Fifteen",
        "Sixteen",
        "Seventeen",
        "Eighteen",
        "Nineteen",
    ]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def _words_under_100(n: int) -> str:
        if n < 20:
            return ones[n]
        return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")

    def _words_under_1000(n: int) -> str:
        if n < 100:
            return _words_under_100(n)
        return ones[n // 100] + " Hundred" + (" " + _words_under_100(n % 100) if n % 100 else "")

    segments: list[str] = []
    num = integer_part
    crore = num // 10000000
    num %= 10000000
    lakh = num // 100000
    num %= 100000
    thousand = num // 1000
    num %= 1000
    hundred = num

    if crore:
        segments.append(_words_under_100(crore) + " Crore")
    if lakh:
        segments.append(_words_under_100(lakh) + " Lakh")
    if thousand:
        segments.append(_words_under_100(thousand) + " Thousand")
    if hundred:
        segments.append(_words_under_1000(hundred))

    result = " ".join(segments).strip()
    if result:
        result += " Rupees"

    if include_paise and paise > 0:
        if result:
            result += " and"
        result += " " + _words_under_100(paise) + " Paise"

    return result.strip() if result else "Zero Rupees"


def format_currency_symbol(amount: float | Decimal, include_symbol: bool = True) -> str:
    """Format amount with ₹ symbol and Indian digit grouping.

    Args:
        amount: The monetary value.
        include_symbol: Whether to prefix ₹ symbol.

    Returns:
        Formatted string.
    """
    formatted = format_indian_rupees(amount)
    if not include_symbol and formatted.startswith("₹"):
        return formatted[1:]
    return formatted
