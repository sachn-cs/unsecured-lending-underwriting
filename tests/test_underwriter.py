"""Tests for UnderwriterService — loan application approval/rejection."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.underwriter.service import UnderwriterService


def svc(bus=None) -> UnderwriterService:
    return UnderwriterService(service_id="underwriter", bus=bus)


def request(svc, bus, **kw) -> None:
    bus.start()
    svc.handle(Event(event_type="underwrite.request", source="test",
                     payload=kw))


class TestUnderwriterApproval:

    def test_approves_low_risk_loan(self) -> None:
        bus = LocalBus()
        approved: list = []
        bus.subscribe(EventType.UNDERWRITER_APPROVED,
                      lambda e: approved.append(e))
        request(svc(bus),
                bus,
                borrower="alice",
                principal=10000,
                default_probability=0.05)
        assert len(approved) == 1
        assert approved[0].payload["borrower"] == "alice"

    def test_rejects_high_default_probability(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED,
                      lambda e: rejected.append(e))
        request(svc(bus),
                bus,
                borrower="bob",
                principal=10000,
                default_probability=0.50)
        assert len(rejected) == 1
        assert "default_probability" in rejected[0].payload["reasons"][0]

    def test_rejects_zero_principal(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED,
                      lambda e: rejected.append(e))
        request(svc(bus),
                bus,
                borrower="carol",
                principal=0,
                default_probability=0.05)
        assert len(rejected) == 1
        assert "principal_must_be_positive" in rejected[0].payload["reasons"]

    def test_rejects_multiple_reasons(self) -> None:
        bus = LocalBus()
        rejected: list = []
        bus.subscribe(EventType.UNDERWRITER_REJECTED,
                      lambda e: rejected.append(e))
        request(svc(bus),
                bus,
                borrower="dave",
                principal=0,
                default_probability=0.50)
        assert len(rejected[0].payload["reasons"]) >= 2

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        approved: list = []
        bus.subscribe(EventType.UNDERWRITER_APPROVED,
                      lambda e: approved.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type="seed.added", source="test", payload={}))
        svc_inst.handle(
            Event(event_type="user.added", source="test", payload={}))
        assert len(approved) == 0


class TestEdgeCases:

    def test_string_values_converted(self) -> None:
        bus = LocalBus()
        approved: list = []
        bus.subscribe(EventType.UNDERWRITER_APPROVED,
                      lambda e: approved.append(e))
        bus.start()
        svc_inst = svc(bus)
        svc_inst.handle(
            Event(event_type="underwrite.request",
                  source="test",
                  payload={
                      "borrower": "eve",
                      "principal": "5000",
                      "default_probability": "0.03"
                  }))
        assert len(approved) == 1
