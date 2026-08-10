"""Underwriting rule engine — declarative policy evaluation.

Defines a rule-based evaluation engine for credit underwriting.
Rules are evaluated against a set of facts (borrower data, credit
bureau, fraud, risk, compliance signals) to produce a decision.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from underwrite.logger import logger


class RuleCategory(str, Enum):
    """Categories for underwriting rules."""

    CREDIT_SCORE = "credit_score"
    DTI = "dti"
    LTV = "ltv"
    FRAUD = "fraud"
    COMPLIANCE = "compliance"
    PRINCIPAL = "principal"
    TENOR = "tenor"
    DEFAULT_PROBABILITY = "default_probability"
    CONCENTRATION = "concentration"
    BUREAU = "bureau"
    RISK = "risk"


class RuleSeverity(str, Enum):
    """Severity levels for rule violations."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DecisionOutcome(str, Enum):
    """Possible outcomes of underwriting evaluation."""

    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    REVIEW = "review"
    ESCALATE = "escalate"
    REJECTED = "rejected"


OPERATORS: dict[str, Callable[..., Any]] = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "between": lambda a, b: b[0] <= a <= b[1],
    "regex": lambda a, b: bool(re.search(b, str(a))),
}


@dataclass(frozen=True, slots=True)
class Rule:
    """A single underwriting rule.

    Attributes:
        rule_id: Unique rule identifier.
        category: Rule category for grouping.
        field: Fact key to evaluate (dot-notation supported).
        operator: Comparison operator (gt, gte, lt, lte, eq, neq, in,
            not_in, between, regex).
        value: Threshold or reference value.
        severity: Impact severity when violated.
        message: Human-readable description.
        enabled: Whether the rule is active.
    """

    rule_id: str
    category: str
    field: str
    operator: str
    value: Any
    severity: str = "medium"
    message: str = ""
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Result of evaluating a single rule.

    Attributes:
        rule_id: Evaluated rule identifier.
        category: Rule category.
        field: Fact field evaluated.
        operator: Comparison operator used.
        threshold: Expected value or threshold.
        actual: Actual value from facts.
        passed: Whether the rule passed.
        severity: Severity of the rule.
        message: Result description.
    """

    rule_id: str
    category: str
    field: str
    operator: str
    threshold: Any
    actual: Any
    passed: bool
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class Policy:
    """A policy groups rules with a logical gate and maps to an action.

    Attributes:
        policy_id: Unique policy identifier.
        description: Human-readable description.
        rule_ids: Set of rule IDs to evaluate.
        logic: Logical gate — ``all``, ``any``, ``none``.
        action: Decision outcome if the policy triggers.
        priority: Evaluation priority (lower = evaluated first).
        enabled: Whether the policy is active.
    """

    policy_id: str
    description: str
    rule_ids: frozenset[str]
    logic: str = "any"
    action: str = "rejected"
    priority: int = 100
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class UnderwritingDecision:
    """Final underwriting decision for an application.

    Attributes:
        application_id: The application identifier.
        outcome: Decision outcome.
        reasons: List of reasons for the decision.
        conditions: List of conditions for conditional approval.
        rule_results: Results of individual rule evaluations.
        policy_results: Results of policy evaluations.
    """

    application_id: str
    outcome: str
    reasons: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    rule_results: list[RuleResult] = field(default_factory=list)
    policy_results: dict[str, bool] = field(default_factory=dict)


def resolve_field(facts: dict[str, Any], field: str) -> Any:
    """Resolve a dot-notation field path against facts dict.

    Args:
        facts: The facts dictionary.
        field: Dot-notation field path.

    Returns:
        The resolved value, or None if not found.
    """
    parts = field.split(".")
    current: Any = facts
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class RuleEngine:
    """Evaluates rules and policies against a set of facts.

    Usage::

        engine = RuleEngine(rules=[...], policies=[...])
        decision = engine.evaluate("APP-001", facts={...})
    """

    def __init__(
        self,
        rules: list[Rule] | None = None,
        policies: list[Policy] | None = None,
    ) -> None:
        self.rules: dict[str, Rule] = {}
        self.policies: list[Policy] = []
        if rules:
            for r in rules:
                self.rules[r.rule_id] = r
        if policies:
            self.policies = sorted(policies, key=lambda p: p.priority)

    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the engine.

        Args:
            rule: The rule to add.
        """
        self.rules[rule.rule_id] = rule

    def add_policy(self, policy: Policy) -> None:
        """Add a policy to the engine.

        Args:
            policy: The policy to add.
        """
        self.policies.append(policy)
        self.policies.sort(key=lambda p: p.priority)

    def evaluate_rule(self, rule: Rule, facts: dict[str, Any]) -> RuleResult:
        """Evaluate a single rule against the given facts.

        Args:
            rule: The rule to evaluate.
            facts: The facts dictionary.

        Returns:
            A RuleResult indicating pass/fail.
        """
        actual = resolve_field(facts, rule.field)
        op_fn = OPERATORS.get(rule.operator)
        if op_fn is None:
            return RuleResult(
                rule_id=rule.rule_id,
                category=rule.category,
                field=rule.field,
                operator=rule.operator,
                threshold=rule.value,
                actual=actual,
                passed=True,
                severity=rule.severity,
                message=f"unknown operator: {rule.operator}",
            )
        try:
            passed = op_fn(actual, rule.value)
        except (TypeError, ValueError, IndexError) as e:
            logger.error("rule {} evaluation error: {} — failing closed", rule.rule_id, e)
            passed = False

        msg = rule.message
        if not msg:
            direction = {
                "gt": "exceeds",
                "gte": "exceeds or equals",
                "lt": "below",
                "lte": "below or equals",
                "eq": "equals",
                "neq": "not equal to",
                "in": "not in allowed set" if not passed else "in allowed set",
                "not_in": "in excluded set" if not passed else "not in excluded set",
                "between": "outside range" if not passed else "within range",
                "regex": "does not match pattern" if not passed else "matches pattern",
            }.get(rule.operator, rule.operator)
            msg = f"{rule.field} {direction} {rule.value} (actual: {actual})"

        return RuleResult(
            rule_id=rule.rule_id,
            category=rule.category,
            field=rule.field,
            operator=rule.operator,
            threshold=rule.value,
            actual=actual,
            passed=passed,
            severity=rule.severity,
            message=msg,
        )

    def evaluate(
        self,
        application_id: str,
        facts: dict[str, Any],
    ) -> UnderwritingDecision:
        """Evaluate all rules and policies against facts.

        Args:
            application_id: The application identifier.
            facts: The facts dictionary.

        Returns:
            An UnderwritingDecision with outcome, reasons, and conditions.
        """
        results: list[RuleResult] = []
        for rule in self.rules.values():
            if not rule.enabled:
                continue
            results.append(self.evaluate_rule(rule, facts))

        policy_results: dict[str, bool] = {}
        for policy in self.policies:
            if not policy.enabled:
                continue
            matched = self.evaluate_policy(policy, results)
            policy_results[policy.policy_id] = matched

        outcome, reasons, conditions = self.resolve_decision(results, policy_results)

        return UnderwritingDecision(
            application_id=application_id,
            outcome=outcome,
            reasons=reasons,
            conditions=conditions,
            rule_results=results,
            policy_results=policy_results,
        )

    def evaluate_policy(
        self,
        policy: Policy,
        results: list[RuleResult],
    ) -> bool:
        """Evaluate a policy against rule results.

        Args:
            policy: The policy to evaluate.
            results: List of rule evaluation results.

        Returns:
            True if the policy gate condition is met.
        """
        policy_rules = [r for r in results if r.rule_id in policy.rule_ids]
        if policy.logic == "all":
            return all(r.passed for r in policy_rules)
        elif policy.logic == "none":
            return not any(r.passed for r in policy_rules)
        else:
            return any(r.passed for r in policy_rules)

    def resolve_decision(
        self,
        results: list[RuleResult],
        policy_results: dict[str, bool],
    ) -> tuple[str, list[str], list[str]]:
        """Resolve the final decision outcome from rule results.

        Args:
            results: List of rule evaluation results.
            policy_results: Results of policy evaluations.

        Returns:
            Tuple of (outcome, reasons, conditions).
        """
        failed = [r for r in results if not r.passed]

        if not failed:
            return DecisionOutcome.APPROVED.value, [], []

        conditions: list[str] = []
        reasons: list[str] = []

        critical: list[RuleResult] = []
        high: list[RuleResult] = []
        medium: list[RuleResult] = []
        low: list[RuleResult] = []
        for r in failed:
            if r.severity == "critical":
                critical.append(r)
            elif r.severity == "high":
                high.append(r)
            elif r.severity == "medium":
                medium.append(r)
            else:
                low.append(r)

        for r in critical:
            reasons.append(f"[{r.rule_id}] {r.message}")

        for r in high:
            if len(high) <= 2:
                conditions.append(f"[{r.rule_id}] {r.message}")
            else:
                reasons.append(f"[{r.rule_id}] {r.message}")

        for r in medium:
            if len(conditions) <= 5:
                conditions.append(f"[{r.rule_id}] {r.message}")

        for r in low:
            if len(conditions) <= 5:
                conditions.append(f"[{r.rule_id}] {r.message}")

        if critical:
            outcome = DecisionOutcome.REJECTED.value
        elif len(high) > 2:
            outcome = DecisionOutcome.ESCALATE.value
        elif high:
            outcome = DecisionOutcome.APPROVED_WITH_CONDITIONS.value
        elif medium:
            outcome = DecisionOutcome.REVIEW.value
        else:
            outcome = DecisionOutcome.APPROVED_WITH_CONDITIONS.value

        return outcome, reasons, conditions
