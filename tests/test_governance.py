"""Tests for GovernanceService — protocol parameter management.

Tests verify behavior through:
  - params property (returns copy of parameters)
  - Emitted GOVERNANCE_EXECUTED events
  - Edge cases: unknown params, non-proposal events, multiple updates
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.governance.service import GovernanceService


def gov(bus=None) -> GovernanceService:
    return GovernanceService(service_id="gov", bus=bus)


class TestGovernanceService:

    def test_default_params(self) -> None:
        svc = gov()
        assert svc.params["protocol_rate"] == 0.10
        assert svc.params["max_delegation_rate"] == 0.05
        assert svc.params["ltv_ratio"] == 0.75
        assert svc.params["min_base_budget"] == 1000.0
        assert svc.params["dlg_cap_ratio"] == 0.05
        assert len(svc.params) == 5

    def test_updates_known_param_on_proposal(self) -> None:
        svc = gov()
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "protocol_rate",
                      "value": 0.15
                  }))
        assert svc.params["protocol_rate"] == 0.15

    def test_updates_multiple_params(self) -> None:
        svc = gov()
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "protocol_rate",
                      "value": 0.12
                  }))
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "ltv_ratio",
                      "value": 0.70
                  }))
        assert svc.params["protocol_rate"] == 0.12
        assert svc.params["ltv_ratio"] == 0.70

    def test_emits_executed_on_successful_update(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.GOVERNANCE_EXECUTED,
                      lambda e: received.append(e))
        svc = gov(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "ltv_ratio",
                      "value": 0.80
                  }))
        assert len(received) == 1
        assert received[0].payload["param"] == "ltv_ratio"
        assert received[0].payload["value"] == 0.80

    def test_ignores_unknown_param(self) -> None:
        svc = gov()
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "nonexistent",
                      "value": 99
                  }))
        assert "nonexistent" not in svc.params

    def test_does_not_emit_for_unknown_param(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.GOVERNANCE_EXECUTED,
                      lambda e: received.append(e))
        svc = gov(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "fake",
                      "value": 1
                  }))
        assert len(received) == 0

    def test_ignores_non_proposal_events(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.GOVERNANCE_EXECUTED,
                      lambda e: received.append(e))
        svc = gov(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={}))
        assert len(received) == 0

    def test_params_returns_copy_not_reference(self) -> None:
        svc = gov()
        params = svc.params
        params["protocol_rate"] = 99.0
        assert svc.params["protocol_rate"] == 0.10

    def test_string_value_converted_to_float(self) -> None:
        svc = gov()
        svc.handle(
            Event(event_type=EventType.GOVERNANCE_PROPOSAL,
                  source="test",
                  payload={
                      "param": "protocol_rate",
                      "value": "0.20"
                  }))
        assert svc.params["protocol_rate"] == 0.20
