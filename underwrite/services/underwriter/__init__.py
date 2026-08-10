# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Underwriting engine — rule and policy-based credit decisions."""

from underwrite.services.underwriter.engine import (
    DecisionOutcome,
    Policy,
    Rule,
    RuleCategory,
    RuleEngine,
    RuleResult,
    RuleSeverity,
    UnderwritingDecision,
)
from underwrite.services.underwriter.underwriter import Handler

__all__ = [
    "DecisionOutcome",
    "Policy",
    "Rule",
    "RuleCategory",
    "RuleEngine",
    "RuleResult",
    "RuleSeverity",
    "UnderwritingDecision",
    "Handler",
]
