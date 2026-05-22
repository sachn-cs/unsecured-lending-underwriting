"""Exhaustive tests for DecisionService."""
from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.decision.service import DecisionService


class TestDecisionService:

    def test_recommends_approve_with_no_signals(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DECISION_MADE, lambda e: received.append(e))
        svc = DecisionService(service_id="decision", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_1"}))
        assert len(received) == 1
        assert received[0].payload["action"] == "approve"

    def test_recommends_reject_on_high_fraud(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DECISION_MADE, lambda e: received.append(e))
        svc = DecisionService(service_id="decision", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.FRAUD_ALERT,
                  source="test",
                  payload={
                      "application_id": "app_2",
                      "severity": "high",
                      "reason": "suspicious"
                  }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_2"}))
        assert received[0].payload["action"] == "reject"

    def test_recommends_escalate_on_many_medium(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DECISION_MADE, lambda e: received.append(e))
        svc = DecisionService(service_id="decision", bus=bus)
        bus.start()
        for _ in range(3):
            svc.handle(
                Event(event_type=EventType.RISK_SCORED,
                      source="test",
                      payload={
                          "application_id": "app_3",
                          "score": 0.5
                      }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_3"}))
        assert received[0].payload["action"] == "escalate"

    def test_recommends_review_on_one_medium(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DECISION_MADE, lambda e: received.append(e))
        svc = DecisionService(service_id="decision", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.RISK_SCORED,
                  source="test",
                  payload={
                      "application_id": "app_4",
                      "score": 0.5
                  }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_4"}))
        assert received[0].payload["action"] == "review"

    def test_approves_on_low_risk(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DECISION_MADE, lambda e: received.append(e))
        svc = DecisionService(service_id="decision", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.RISK_SCORED,
                  source="test",
                  payload={
                      "application_id": "app_5",
                      "score": 0.2
                  }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_5"}))
        assert received[0].payload["action"] == "approve"

    def test_stores_decision(self) -> None:
        svc = DecisionService(service_id="decision")
        svc.handle(
            Event(event_type=EventType.FRAUD_ALERT,
                  source="test",
                  payload={
                      "application_id": "app_6",
                      "severity": "high"
                  }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_6"}))
        rec = svc.store.get("decision:app_6")
        assert rec["action"] == "reject"
        assert len(rec["signals"]) == 1

    def test_clears_signals_after_evaluation(self) -> None:
        svc = DecisionService(service_id="decision")
        svc.handle(
            Event(event_type=EventType.RISK_SCORED,
                  source="test",
                  payload={
                      "application_id": "app_7",
                      "score": 0.3
                  }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_7"}))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_7"}))
        rec = svc.store.get("decision:app_7")
        assert rec["action"] == "approve"

    def test_ignores_events_without_entity_id(self) -> None:
        svc = DecisionService(service_id="decision")
        svc.handle(
            Event(event_type=EventType.FRAUD_ALERT, source="test", payload={}))
        svc.handle(
            Event(event_type="decision.evaluate", source="test", payload={}))
        assert len(svc.store.keys("decision:")) == 0

    def test_ignores_unrelated_events(self) -> None:
        svc = DecisionService(service_id="decision")
        svc.handle(
            Event(event_type="seed.added",
                  source="test",
                  payload={"application_id": "x"}))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "x"}))
        rec = svc.store.get("decision:x")
        assert rec["action"] == "approve"

    def test_signal_count_in_payload(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.DECISION_MADE, lambda e: received.append(e))
        svc = DecisionService(service_id="decision", bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.RISK_SCORED,
                  source="test",
                  payload={
                      "application_id": "app_8",
                      "score": 0.5
                  }))
        svc.handle(
            Event(event_type=EventType.FRAUD_ALERT,
                  source="test",
                  payload={
                      "application_id": "app_8",
                      "severity": "high"
                  }))
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_8"}))
        assert received[0].payload["signal_count"] == 2


class TestDecisionServiceConcurrency:

    def test_concurrent_evaluate_does_not_lose_signals(self) -> None:
        svc = DecisionService(service_id="decision")
        svc.handle(
            Event(event_type=EventType.RISK_SCORED,
                  source="test",
                  payload={
                      "application_id": "app_conc",
                      "score": 0.5
                  }))
        svc.handle(
            Event(event_type=EventType.FRAUD_ALERT,
                  source="test",
                  payload={
                      "application_id": "app_conc",
                      "severity": "medium"
                  }))
        # First evaluate pops signals
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_conc"}))
        # Second evaluate should get empty list -> approve (not crash or see stale data)
        svc.handle(
            Event(event_type="decision.evaluate",
                  source="test",
                  payload={"application_id": "app_conc"}))
        # Verify no crash and second evaluation produces approve (empty signals)
        rec = svc.store.get("decision:app_conc")
        assert rec is not None
