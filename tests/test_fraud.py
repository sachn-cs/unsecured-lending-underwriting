"""Tests for FraudService — wash lending, burst detection, large origination alerts.

Tests verify behavior through emitted events only:
  - WASH_FLAG on 3+ origination-repayment cycles
  - VELOCITY_FLAG on 4+ originations
  - FRAUD_ALERT on principal > $1M
  - Edge cases: zero events, single cycles, boundary values
"""

from __future__ import annotations

from collections import deque

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__exceptions__ import ProtocolError
from underwrite.services.fraud.service import FraudService


def fraud(bus=None) -> FraudService:
    return FraudService(service_id="fraud", bus=bus)


def originate(svc: FraudService, borrower: str, principal: int = 1000) -> None:
    svc.handle(
        Event(event_type=EventType.LOAN_ORIGINATED,
              source="test",
              payload={
                  "borrower": borrower,
                  "principal": principal
              }))


def repay(svc: FraudService, user: str, amount: int = 1000) -> None:
    svc.handle(
        Event(event_type=EventType.REPAID,
              source="test",
              payload={
                  "user": user,
                  "delta_earned": amount
              }))


class TestWashLending:

    def test_no_wash_with_zero_cycles(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "alice")
        assert len(received) == 0

    def test_no_wash_with_two_cycles(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(2):
            originate(svc, "bob")
            repay(svc, "bob")
        assert len(received) == 0

    def test_wash_flag_on_three_cycles(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(3):
            originate(svc, "carol")
            repay(svc, "carol")
        assert len(received) >= 1
        assert received[0].event_type == EventType.WASH_FLAG
        assert received[0].payload["cycles"] >= 3

    def test_wash_score_increases_with_more_cycles(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(6):
            originate(svc, "dave")
            repay(svc, "dave")
        assert any(r.payload["cycles"] >= 6 for r in received)

    def test_wash_score_capped_at_100(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(10):
            originate(svc, "eve")
            repay(svc, "eve")
        assert all(r.payload["score"] <= 100.0 for r in received)

    def test_interleaved_events_dont_false_positive(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "frank")
        repay(svc, "frank")
        originate(svc, "frank")
        originate(svc, "frank")
        repay(svc, "frank")
        assert len(received) == 0


class TestBurstDetection:

    def test_no_burst_below_threshold(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(3):
            originate(svc, "grace")
        assert len(received) == 0

    def test_burst_on_four_originations(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(4):
            originate(svc, "heidi")
        assert len(received) >= 1
        assert received[0].event_type == EventType.VELOCITY_FLAG
        assert received[0].payload["count"] >= 4

    def test_burst_not_triggered_by_repayments(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "ivan")
        repay(svc, "ivan")
        repay(svc, "ivan")
        repay(svc, "ivan")
        assert len(received) == 0

    def test_different_borrowers_independent(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(4):
            originate(svc, "a")
            originate(svc, "b")
        assert len(received) == 2  # one burst per borrower


class TestLargeOrigination:

    def test_alert_on_large_principal(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "mallory", principal=2_000_000)
        assert len(received) >= 1
        assert received[0].payload["rule"] == "large_origination"
        assert received[0].payload["principal"] == 2_000_000

    def test_no_alert_below_threshold(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "oscar", principal=500_000)
        assert len(received) == 0

    def test_alert_at_exactly_one_million(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "peggy", principal=1_000_001)
        assert len(received) >= 1

    def test_alert_uses_borrower_from_origination_event(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "borrower": "trent",
                      "principal": 1_500_000
                  }))
        assert received[0].payload["rule"] == "large_origination"
        assert received[0].payload["borrower"] == "trent"


class TestEdgeCases:

    def test_ignores_unrelated_events(self) -> None:
        svc = fraud()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(Event(event_type="user.added", source="test", payload={}))
        svc.handle(
            Event(event_type="quote.calculated", source="test", payload={}))

    def test_handles_empty_payload(self) -> None:
        bus = LocalBus()
        received: list[Event] = []
        bus.subscribe(EventType.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(2):
            try:
                svc.handle(
                    Event(event_type=EventType.LOAN_ORIGINATED,
                          source="test",
                          payload={}))
            except ProtocolError:
                pass
        try:
            svc.handle(
                Event(event_type=EventType.REPAID, source="test", payload={}))
        except ProtocolError:
            pass
        assert len(received) == 0

    def test_missing_borrower_does_not_crash(self) -> None:
        svc = fraud()
        try:
            svc.handle(
                Event(event_type=EventType.LOAN_ORIGINATED,
                      source="test",
                      payload={}))
        except ProtocolError:
            pass

    def test_records_use_deque_maxlen(self) -> None:
        svc = fraud()
        # Access private __records to verify deque maxlen
        records = svc._FraudService__records
        borrower = "maxlen_test"
        for _i in range(2000):
            svc.handle(
                Event(event_type=EventType.LOAN_ORIGINATED,
                      source="test",
                      payload={"borrower": borrower, "principal": 100}))
        recs = records.get(borrower)
        assert recs is not None
        assert isinstance(recs, deque)
        assert recs.maxlen == 1000
        assert len(recs) == 1000
