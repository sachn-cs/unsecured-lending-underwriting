"""Tests for PricingService — dynamic rate and fee computation."""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.pricing.service import PricingService


def svc(bus=None) -> PricingService:
    return PricingService(service_id="pricing", bus=bus)


def request(svc, bus, **kw) -> None:
    bus.start()
    svc.handle(Event(event_type="pricing.request", source="test", payload=kw))


class TestPricing:

    def test_computes_base_rate_for_low_risk(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus),
                bus,
                borrower="alice",
                principal=10000,
                default_probability=0.02)
        assert received[0].payload["interest_rate"] == 0.09
        assert received[0].payload["origination_fee"] == 100.0

    def test_higher_risk_higher_rate(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus),
                bus,
                borrower="bob",
                principal=10000,
                default_probability=0.20)
        assert received[0].payload["interest_rate"] > 0.09

    def test_origination_fee_is_one_percent(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus),
                bus,
                borrower="carol",
                principal=50000,
                default_probability=0.05)
        assert received[0].payload["origination_fee"] == 500.0

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PRICING_COMPUTED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Event(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0

    def test_missing_dp_defaults(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(EventType.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus), bus, borrower="dave", principal=10000)
        assert received[0].payload["risk_premium"] == 0.01
