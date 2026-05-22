"""Tests for QuoteService — loan pricing and break-even rate calculation.

Tests verify behavior through emitted QUOTE_CALCULATED events.
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.quote.service import QuoteService


def quote(bus=None) -> QuoteService:
    return QuoteService(service_id="quote", bus=bus)


def emit_quote(svc, **overrides) -> None:
    payload = {
        "borrower": "alice",
        "principal": 10000,
        "term": 12,
        "default_probability": 0.02,
        "protocol_rate": 0.10,
        "max_delegation_rate": 0.05,
    }
    payload.update(overrides)
    svc.handle(Event(event_type="quote", source="test", payload=payload))


class TestProtocolPremium:

    def test_calculates_protocol_premium(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, principal=10000, term=12, protocol_rate=0.10)
        assert received[0].payload["protocol_premium"] == 12000.0
        assert received[0].payload["total_interest"] == 12000.0

    def test_zero_principal_zero_premium(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, principal=0, term=12, protocol_rate=0.10)
        assert received[0].payload["protocol_premium"] == 0.0

    def test_zero_term_rejected(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        from underwrite.__exceptions__ import ProtocolError
        try:
            emit_quote(svc, principal=10000, term=0, protocol_rate=0.10)
        except ProtocolError:
            pass
        assert len(received) == 0

    def test_zero_rate_zero_premium(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, protocol_rate=0.0)
        assert received[0].payload["protocol_premium"] == 0.0

    def test_large_principal_large_premium(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, principal=1_000_000, term=12, protocol_rate=0.10)
        assert received[0].payload["protocol_premium"] == 1_200_000.0


class TestBreakEvenRate:

    def test_normal_dp_gives_positive_break_even(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, default_probability=0.05, term=6)
        assert received[0].payload["break_even_rate"] > 0

    def test_zero_dp_means_zero_break_even(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, default_probability=0.0, term=12)
        assert received[0].payload["break_even_rate"] == 0.0

    def test_dp_of_one_means_zero_break_even(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, default_probability=1.0, term=12)
        assert received[0].payload["break_even_rate"] == 0.0

    def test_high_dp_capped_at_one_million(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, default_probability=0.9999999, term=1)
        assert received[0].payload["break_even_rate"] == 1_000_000.0

    def test_positive_dp_short_term(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc, default_probability=0.50, term=1)
        ber = received[0].payload["break_even_rate"]
        assert 0.5 < ber < 1.5


class TestFieldPassthrough:

    def test_all_input_fields_in_output(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        emit_quote(svc,
                   borrower="frank",
                   principal=20000,
                   term=24,
                   default_probability=0.03,
                   protocol_rate=0.12,
                   max_delegation_rate=0.06)
        p = received[0].payload
        assert p["borrower"] == "frank"
        assert p["principal"] == 20000.0
        assert p["term"] == 24.0
        assert p["default_probability"] == 0.03
        assert p["protocol_rate"] == 0.12
        assert p["max_delegation_rate"] == 0.06

    def test_defaults_when_fields_missing(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="quote",
                  source="test",
                  payload={"borrower": "grace"}))
        p = received[0].payload
        assert p["principal"] == 0.0
        assert p["term"] == 1.0
        assert p["default_probability"] == 0.02
        assert p["protocol_rate"] == 0.10
        assert p["max_delegation_rate"] == 0.05


class TestEdgeCases:

    def test_ignores_non_quote_events(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(
            Event(event_type="loan.originated", source="test", payload={}))
        assert len(received) == 0

    def test_string_values_converted(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.QUOTE_CALCULATED, lambda e: received.append(e))
        svc = quote(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type="quote",
                  source="test",
                  payload={
                      "borrower": "h",
                      "principal": "5000",
                      "term": "6",
                      "default_probability": "0.04",
                      "protocol_rate": "0.08",
                  }))
        assert received[0].payload["principal"] == 5000.0
        assert received[0].payload["term"] == 6.0
        assert received[0].payload["default_probability"] == 0.04
        assert received[0].payload["protocol_rate"] == 0.08
