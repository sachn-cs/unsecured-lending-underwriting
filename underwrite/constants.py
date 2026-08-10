# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Domain-wide named constants.

Centralizes magic numbers that appear across services so they are
named once and reused. AGENTS.md forbids unexplained literals:
every important constant deserves a name.
"""

from decimal import Decimal

__all__ = [
    "DAYS_PER_YEAR",
    "HOURS_PER_DAY",
    "MAX_PAYLOAD_KEYS",
    "MONEY_QUANTUM",
    "PAISE_PER_RUPEE",
    "RATE_QUANTUM",
    "RETRY_BASE_DELAY_SECONDS",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_MINUTE",
]

DAYS_PER_YEAR: int = 365

HOURS_PER_DAY: int = 24

MAX_PAYLOAD_KEYS: int = 1000

MONEY_QUANTUM: Decimal = Decimal("0.01")

PAISE_PER_RUPEE: int = 100

RATE_QUANTUM: Decimal = Decimal("0.01")

RETRY_BASE_DELAY_SECONDS: float = 0.05

SECONDS_PER_DAY: int = 86_400

SECONDS_PER_HOUR: int = 3_600

SECONDS_PER_MINUTE: int = 60
