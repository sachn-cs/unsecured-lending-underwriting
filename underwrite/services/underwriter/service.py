"""Underwriter — evaluates loan applications using rule engine.

Enhanced service that aggregates signals from risk, fraud, credit bureau,
AML/KYC and applies configurable rules to produce graded decisions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.__logger__ import logger
from underwrite.services.base import StatefulService
from underwrite.services.persistence import TypedStoreRepository
from underwrite.services.underwriter.engine import (
    DecisionOutcome,
    Policy,
    Rule,
    RuleCategory,
    RuleEngine,
    RuleSeverity,
    UnderwritingDecision,
)
from underwrite.validate import get_finite, get_non_empty

DEFAULT_RULES: list[Rule] = [
    Rule(
        rule_id="principal_positive",
        category=RuleCategory.PRINCIPAL.value,
        field="principal",
        operator="gt",
        value=0,
        severity=RuleSeverity.CRITICAL.value,
        message="Principal must be positive",
    ),
    Rule(
        rule_id="principal_max",
        category=RuleCategory.PRINCIPAL.value,
        field="principal",
        operator="lte",
        value=10_000_000,
        severity=RuleSeverity.HIGH.value,
        message="Principal exceeds maximum",
    ),
    Rule(
        rule_id="principal_min",
        category=RuleCategory.PRINCIPAL.value,
        field="principal",
        operator="gte",
        value=1_000,
        severity=RuleSeverity.HIGH.value,
        message="Principal below minimum",
    ),
    Rule(
        rule_id="default_probability_max",
        category=RuleCategory.DEFAULT_PROBABILITY.value,
        field="default_probability",
        operator="lte",
        value=0.25,
        severity=RuleSeverity.CRITICAL.value,
        message="Default probability exceeds threshold",
    ),
    Rule(
        rule_id="credit_score_min",
        category=RuleCategory.CREDIT_SCORE.value,
        field="credit_score",
        operator="gte",
        value=650,
        severity=RuleSeverity.HIGH.value,
        message="Credit score below minimum",
    ),
    Rule(
        rule_id="dti_max",
        category=RuleCategory.DTI.value,
        field="dti_ratio",
        operator="lte",
        value=0.5,
        severity=RuleSeverity.HIGH.value,
        message="Debt-to-income ratio exceeds limit",
    ),
    Rule(
        rule_id="ltv_max",
        category=RuleCategory.LTV.value,
        field="ltv_ratio",
        operator="lte",
        value=0.8,
        severity=RuleSeverity.HIGH.value,
        message="Loan-to-value ratio exceeds limit",
    ),
    Rule(
        rule_id="tenor_max",
        category=RuleCategory.TENOR.value,
        field="tenor_months",
        operator="lte",
        value=360,
        severity=RuleSeverity.MEDIUM.value,
        message="Tenor exceeds maximum",
    ),
    Rule(
        rule_id="fraud_flag",
        category=RuleCategory.FRAUD.value,
        field="fraud_signals",
        operator="eq",
        value=0,
        severity=RuleSeverity.CRITICAL.value,
        message="Fraud signals detected",
    ),
    Rule(
        rule_id="aml_not_frozen",
        category=RuleCategory.COMPLIANCE.value,
        field="aml_status",
        operator="neq",
        value="frozen",
        severity=RuleSeverity.CRITICAL.value,
        message="AML status is frozen",
    ),
    Rule(
        rule_id="kyc_verified",
        category=RuleCategory.COMPLIANCE.value,
        field="kyc_status",
        operator="eq",
        value="verified",
        severity=RuleSeverity.CRITICAL.value,
        message="KYC not verified",
    ),
]

DEFAULT_POLICIES: list[Policy] = [
    Policy(
        policy_id="auto_approve",
        description="Auto-approve when no high-severity rules fail",
        rule_ids=frozenset(r.rule_id for r in DEFAULT_RULES),
        logic="all",
        action=DecisionOutcome.APPROVED.value,
        priority=10,
    ),
]


class UnderwriterHandler(StatefulService):
    """Evaluates loan applications using a configurable rule engine.

    Accumulates facts from multiple signal events (risk, fraud, credit bureau,
    AML, KYC) and evaluates rules to produce a graded decision.
    """

    MAX_APPLICATIONS: int = 10000

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.engine = RuleEngine(rules=DEFAULT_RULES, policies=DEFAULT_POLICIES)
        self.applications: dict[str, dict[str, Any]] = {}
        self.repo: TypedStoreRepository[dict[str, Any]] = self.store_repo("underwriter", dict)

    def start(self) -> None:
        """Load persisted applications when the service starts."""
        super().start()
        loaded = self.repo.load(default={})
        if loaded:
            self.applications = loaded.get("applications", {})

    def _evict_if_full(self) -> None:
        if len(self.applications) >= self.MAX_APPLICATIONS:
            excess = len(self.applications) - self.MAX_APPLICATIONS + 1
            for _ in range(min(excess, max(1, self.MAX_APPLICATIONS // 10))):
                self.applications.pop(next(iter(self.applications)), None)

    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the engine.

        Args:
            rule: The rule to add.
        """
        self.engine.add_rule(rule)

    def add_policy(self, policy: Policy) -> None:
        """Add a policy to the engine.

        Args:
            policy: The policy to add.
        """
        self.engine.add_policy(policy)

    def handle(self, event: Event) -> None:
        """Process events that contribute to underwriting facts.

        Args:
            event: The incoming domain event.
        """
        if event.event_type == EventType.UNDERWRITE_REQUEST:
            self.handle_request(event)
        elif event.event_type == EventType.RISK_SCORED:
            self.accumulate(event, "risk_score", lambda p: p.get("score", 0))
        elif event.event_type == EventType.FRAUD_ALERT:
            self.accumulate_signal(event, "fraud_signals")
        elif event.event_type == EventType.CREDIT_BUREAU_CHECKED:
            self.accumulate_bureau(event)
        elif event.event_type == EventType.AML_CLEARED:
            self.accumulate(event, "aml_status", lambda p: "cleared")
        elif event.event_type == EventType.AML_FROZEN:
            self.accumulate(event, "aml_status", lambda p: "frozen")
        elif event.event_type == EventType.KYC_VERIFIED:
            self.accumulate(event, "kyc_status", lambda p: "verified")
        elif event.event_type == EventType.KYC_REJECTED:
            self.accumulate(event, "kyc_status", lambda p: "rejected")
        elif event.event_type == EventType.DECISION_MADE:
            self.accumulate(event, "decision_action", lambda p: p.get("action", ""))

    def accumulate(
        self,
        event: Event,
        key: str,
        extractor: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Accumulate a fact from an event payload.

        Args:
            event: The incoming event.
            key: The fact key to store.
            extractor: Callable to extract the value from the payload.
        """
        app_id = event.payload.get("application_id", event.payload.get("entity_id", ""))
        if not app_id:
            app_id = event.payload.get("loan_id", "")
        if not app_id:
            return
        with self.state_lock:
            if app_id not in self.applications:
                self._evict_if_full()
                self.applications[app_id] = {}
            self.applications[app_id][key] = extractor(event.payload)
            self.sync()

    def accumulate_signal(self, event: Event, key: str) -> None:
        """Accumulate a signal counter from an event payload.

        Args:
            event: The incoming event.
            key: The fact key to increment.
        """
        app_id = event.payload.get("application_id", event.payload.get("entity_id", ""))
        if not app_id:
            return
        with self.state_lock:
            if app_id not in self.applications:
                self._evict_if_full()
                self.applications[app_id] = {}
            current = self.applications[app_id].get(key, 0)
            self.applications[app_id][key] = current + 1
            self.sync()

    def accumulate_bureau(self, event: Event) -> None:
        """Accumulate credit bureau data from an event payload.

        Args:
            event: The CREDIT_BUREAU_CHECKED event.
        """
        app_id = event.payload.get("application_id", event.payload.get("entity_id", ""))
        if not app_id:
            app_id = event.payload.get("pan", "")
        if not app_id:
            return
        with self.state_lock:
            if app_id not in self.applications:
                self._evict_if_full()
                self.applications[app_id] = {}
            self.applications[app_id].update(
                {
                    "credit_score": event.payload.get("score", 0),
                    "credit_utilization_pct": event.payload.get("credit_utilization_pct", 0),
                    "delinquent_accounts": event.payload.get("delinquent_accounts", 0),
                }
            )
            self.sync()

    def handle_request(self, event: Event) -> None:
        """Handle an underwriting request event.

        Args:
            event: The UNDERWRITE_REQUEST event.
        """
        p = event.payload
        app_id: str = p.get("application_id", "") or event.correlation_id
        borrower: str = get_non_empty(p, "borrower", "")
        principal: float = get_finite(p, "principal", 0.0)
        dp: float = get_finite(p, "default_probability", 0.0)

        if not borrower:
            logger.warning("underwrite.request missing borrower")
            return

        with self.state_lock:
            if app_id not in self.applications:
                self._evict_if_full()
            facts: dict[str, Any] = self.applications.get(app_id, {})
            facts.update(
                {
                    "application_id": app_id,
                    "borrower": borrower,
                    "principal": principal,
                    "default_probability": dp,
                    "tenor_months": p.get("tenor_months", 0),
                    "dti_ratio": p.get("dti_ratio", 0.0),
                    "ltv_ratio": p.get("ltv_ratio", 0.0),
                    "credit_score": facts.get("credit_score", p.get("credit_score", 0)),
                    "fraud_signals": facts.get("fraud_signals", 0),
                    "aml_status": facts.get("aml_status", p.get("aml_status", "")),
                    "kyc_status": facts.get("kyc_status", p.get("kyc_status", "")),
                    "purpose": p.get("purpose", ""),
                }
            )
            self.applications[app_id] = facts
            self.sync()

        decision = self.engine.evaluate(app_id, facts)
        self.emit_decision(decision, event.correlation_id)

    def emit_decision(
        self,
        decision: UnderwritingDecision,
        correlation_id: str,
    ) -> None:
        """Emit the appropriate decision event based on outcome.

        Args:
            decision: The underwriting decision.
            correlation_id: Correlation ID for emitted events.
        """
        payload: dict[str, Any] = {
            "application_id": decision.application_id,
            "outcome": decision.outcome,
            "reasons": decision.reasons,
            "conditions": decision.conditions,
            "rule_results": [
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": r.severity,
                    "message": r.message,
                }
                for r in decision.rule_results
            ],
        }

        for r in decision.rule_results:
            if not r.passed:
                self.emit(
                    EventType.UNDERWRITE_RULE_VIOLATED,
                    {
                        "application_id": decision.application_id,
                        "rule_id": r.rule_id,
                        "category": r.category,
                        "severity": r.severity,
                        "message": r.message,
                        "actual": r.actual,
                        "threshold": r.threshold,
                    },
                    correlation_id=correlation_id,
                )

        if decision.outcome == DecisionOutcome.APPROVED.value:
            self.emit(EventType.UNDERWRITER_APPROVED, payload, correlation_id=correlation_id)
        elif decision.outcome == DecisionOutcome.APPROVED_WITH_CONDITIONS.value:
            self.emit(
                EventType.UNDERWRITER_CONDITIONAL_APPROVED,
                payload,
                correlation_id=correlation_id,
            )
        elif decision.outcome == DecisionOutcome.REVIEW.value:
            self.emit(EventType.UNDERWRITER_REVIEW, payload, correlation_id=correlation_id)
        elif decision.outcome == DecisionOutcome.ESCALATE.value:
            self.emit(EventType.UNDERWRITER_ESCALATED, payload, correlation_id=correlation_id)
        else:
            self.emit(EventType.UNDERWRITER_REJECTED, payload, correlation_id=correlation_id)

    def get_application(self, app_id: str) -> dict[str, Any] | None:
        """Return the accumulated facts for an application.

        Args:
            app_id: The application identifier.

        Returns:
            Facts dict or None.
        """
        with self.state_lock:
            return self.applications.get(app_id)

    def evaluate_facts(
        self,
        app_id: str,
        facts: dict[str, Any],
    ) -> UnderwritingDecision:
        """Evaluate facts against the rule engine.

        Args:
            app_id: The application identifier.
            facts: The facts dictionary.

        Returns:
            An UnderwritingDecision.
        """
        return self.engine.evaluate(app_id, facts)

    def health_check(self) -> dict[str, Any]:
        """Return health metrics for the underwriter.

        Returns:
            Dict with base health, application count, and rule count.
        """
        base = super().health_check()
        base["applications_in_progress"] = len(self.applications)
        base["rules_loaded"] = len(self.engine.rules)
        return base

    def sync(self) -> None:
        """Persist applications to the store."""
        self.repo.save({"applications": self.applications})
