"""Tests for UnderwriterHandler — loan application approval/rejection."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.underwriter.handler import UnderwriterHandler


def svc(bus=None) -> UnderwriterHandler:
    return UnderwriterHandler(service_id="underwriter", bus=bus)


def request(svc, bus, **kw) -> None:
    bus.start()
    svc.handle(Event(event_type="underwrite.request", source="test", payload=kw))


class TestUnderwriterApproval:
    def test_approves_low_risk_loan(self) -> None:
        bus = LocalBus()
        approved: list = []
        bus.subscribe(EventType.UNDERWRITER_APPROVED, lambda e: approved.append(e))
        request(
            svc(bus),
            bus,
            application_id="APP1",
            borrower="alice",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(approved) == 1
        assert approved[0].payload["outcome"] == "approved"
        assert approved[0].payload["application_id"] is not None

    def test_rejects_high_default_probability(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        request(svc(bus), bus, application_id="APP2", borrower="bob", principal=10000, default_probability=0.50)
        assert len(rejected) == 1
        assert "default_probability_max" in rejected[0].payload["reasons"][0]

    def test_rejects_zero_principal(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        request(svc(bus), bus, application_id="APP3", borrower="carol", principal=0, default_probability=0.05)
        assert len(rejected) == 1
        assert "principal_positive" in rejected[0].payload["reasons"][0]

    def test_rejects_multiple_reasons(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        request(svc(bus), bus, application_id="APP4", borrower="dave", principal=0, default_probability=0.50)
        assert len(rejected[0].payload["reasons"]) >= 2

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        approved: list = []
        bus.subscribe(EventType.UNDERWRITER_APPROVED, lambda e: approved.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Event(event_type="seed.added", source="test", payload={}))
        svc_inst.handle(Event(event_type="user.added", source="test", payload={}))
        assert len(approved) == 0


class TestEdgeCases:
    def test_string_values_converted(self) -> None:
        """Numeric fact values arrive as strings; the engine should now
        fail closed (no approval) rather than silently passing a
        malformed rule evaluation."""
        bus = LocalBus()
        approved: list = []
        conditional: list = []
        bus.subscribe(EventType.UNDERWRITER_APPROVED, lambda e: approved.append(e))
        bus.subscribe(EventType.UNDERWRITER_CONDITIONAL_APPROVED, lambda e: conditional.append(e))
        bus.start()
        svc_inst = svc(bus)
        svc_inst.handle(
            Event(
                event_type="underwrite.request",
                source="test",
                payload={
                    "application_id": "APP5",
                    "borrower": "eve",
                    "principal": "5000",
                    "default_probability": "0.03",
                    "credit_score": "720",
                    "aml_status": "cleared",
                    "kyc_status": "verified",
                },
            )
        )
        assert len(approved) == 0
        assert len(conditional) == 1


class TestConditionalApproval:
    def test_approves_with_conditions_when_low_credit(self) -> None:
        bus = LocalBus()
        cond: list = []
        bus.subscribe(EventType.UNDERWRITER_CONDITIONAL_APPROVED, lambda e: cond.append(e))
        request(
            svc(bus),
            bus,
            application_id="APP10",
            borrower="alice",
            principal=10000,
            default_probability=0.05,
            credit_score=600,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(cond) == 1
        assert "credit_score_min" in cond[0].payload["conditions"][0]

    def test_approves_with_conditions_when_high_dti(self) -> None:
        bus = LocalBus()
        cond: list = []
        bus.subscribe(EventType.UNDERWRITER_CONDITIONAL_APPROVED, lambda e: cond.append(e))
        request(
            svc(bus),
            bus,
            application_id="APP11",
            borrower="bob",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            dti_ratio=0.6,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(cond) == 1

    def test_approves_with_conditions_when_high_ltv(self) -> None:
        bus = LocalBus()
        cond: list = []
        bus.subscribe(EventType.UNDERWRITER_CONDITIONAL_APPROVED, lambda e: cond.append(e))
        request(
            svc(bus),
            bus,
            application_id="APP12",
            borrower="carol",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            ltv_ratio=0.9,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(cond) == 1


class TestReviewAndEscalate:
    def test_review_when_medium_severity(self) -> None:
        bus = LocalBus()
        review: list = []
        bus.subscribe(EventType.UNDERWRITER_REVIEW, lambda e: review.append(e))
        request(
            svc(bus),
            bus,
            application_id="APP20",
            borrower="alice",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            tenor_months=480,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(review) == 1

    def test_rejects_when_fraud_signals(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        svc_inst = svc(bus)
        svc_inst.handle(
            Event(event_type=EventType.FRAUD_ALERT, source="fraud", payload={"entity_id": "APP30", "severity": "high"})
        )
        request(
            svc_inst,
            bus,
            application_id="APP30",
            borrower="mallory",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(rejected) == 1

    def test_rejected_when_aml_frozen(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        svc_inst = svc(bus)
        svc_inst.handle(Event(event_type=EventType.AML_FROZEN, source="compliance", payload={"entity_id": "APP31"}))
        request(
            svc_inst,
            bus,
            application_id="APP31",
            borrower="oscar",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(rejected) == 1

    def test_rejected_when_kyc_rejected(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        svc_inst = svc(bus)
        svc_inst.handle(Event(event_type=EventType.KYC_REJECTED, source="compliance", payload={"entity_id": "APP32"}))
        request(
            svc_inst,
            bus,
            application_id="APP32",
            borrower="peggy",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(rejected) == 1


class TestSignalAccumulation:
    def test_accumulates_risk_score(self) -> None:
        s = svc()
        s.handle(
            Event(event_type=EventType.RISK_SCORED, source="risk", payload={"application_id": "APP40", "score": 0.75})
        )
        app = s.get_application("APP40")
        assert app is not None
        assert app["risk_score"] == 0.75

    def test_accumulates_credit_bureau(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.CREDIT_BUREAU_CHECKED,
                source="credit_bureau",
                payload={
                    "pan": "ABCDE1234F",
                    "score": 720,
                    "delinquent_accounts": 2,
                },
            )
        )
        app = s.get_application("ABCDE1234F")
        assert app is not None
        assert app["credit_score"] == 720
        assert app["delinquent_accounts"] == 2

    def test_accumulates_fraud_signals(self) -> None:
        s = svc()
        s.handle(
            Event(event_type=EventType.FRAUD_ALERT, source="fraud", payload={"entity_id": "APP41", "severity": "high"})
        )
        s.handle(
            Event(event_type=EventType.FRAUD_ALERT, source="fraud", payload={"entity_id": "APP41", "severity": "low"})
        )
        app = s.get_application("APP41")
        assert app is not None
        assert app["fraud_signals"] == 2


class TestRuleEngine:
    def test_rule_engine_basic_evaluation(self) -> None:
        from underwrite.services.underwriter.engine import Rule, RuleCategory, RuleEngine, RuleSeverity

        engine = RuleEngine(
            rules=[
                Rule(
                    rule_id="test_rule",
                    category=RuleCategory.CREDIT_SCORE.value,
                    field="credit_score",
                    operator="gte",
                    value=650,
                    severity=RuleSeverity.HIGH.value,
                ),
            ]
        )
        decision = engine.evaluate("APP50", {"credit_score": 700})
        assert len(decision.rule_results) == 1
        assert decision.rule_results[0].passed is True

    def test_rule_engine_detects_failure(self) -> None:
        from underwrite.services.underwriter.engine import Rule, RuleCategory, RuleEngine, RuleSeverity

        engine = RuleEngine(
            rules=[
                Rule(
                    rule_id="test_rule",
                    category=RuleCategory.CREDIT_SCORE.value,
                    field="credit_score",
                    operator="gte",
                    value=650,
                    severity=RuleSeverity.CRITICAL.value,
                ),
            ]
        )
        decision = engine.evaluate("APP51", {"credit_score": 600})
        assert decision.rule_results[0].passed is False
        assert decision.outcome == "rejected"

    def test_rule_engine_custom_rule(self) -> None:
        from underwrite.services.underwriter.engine import Rule, RuleCategory, RuleSeverity

        s = svc()
        s.add_rule(
            Rule(
                rule_id="custom_min_principal",
                category=RuleCategory.PRINCIPAL.value,
                field="principal",
                operator="gte",
                value=50000,
                severity=RuleSeverity.CRITICAL.value,
                message="Principal must be at least 50000",
            )
        )
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED, lambda e: rejected.append(e))
        s = svc(bus)
        s.add_rule(
            Rule(
                rule_id="custom_min_principal",
                category=RuleCategory.PRINCIPAL.value,
                field="principal",
                operator="gte",
                value=50000,
                severity=RuleSeverity.CRITICAL.value,
                message="Principal must be at least 50000",
            )
        )
        request(
            s,
            bus,
            application_id="APP60",
            borrower="alice",
            principal=10000,
            default_probability=0.05,
            credit_score=720,
            aml_status="cleared",
            kyc_status="verified",
        )
        assert len(rejected) == 1
        assert "custom_min_principal" in rejected[0].payload["reasons"][0]


class TestRuleViolationEvents:
    def test_emits_rule_violations(self) -> None:
        bus = LocalBus()
        violations: list = []
        bus.subscribe(EventType.UNDERWRITE_RULE_VIOLATED, lambda e: violations.append(e))
        request(
            svc(bus),
            bus,
            application_id="APP70",
            borrower="alice",
            principal=10000,
            default_probability=0.50,
            credit_score=720,
        )
        assert len(violations) >= 1
        rule_ids = {v.payload["rule_id"] for v in violations}
        assert "default_probability_max" in rule_ids


class TestHealthCheck:
    def test_health_returns_counts(self) -> None:
        s = svc()
        s.handle(
            Event(
                event_type=EventType.UNDERWRITE_REQUEST,
                source="test",
                payload={
                    "application_id": "APP99",
                    "borrower": "alice",
                    "principal": 10000,
                    "default_probability": 0.05,
                },
            )
        )
        health = s.health_check()
        assert health["applications_in_progress"] == 1
        assert health["rules_loaded"] >= 10
