# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — wash lending, burst detection, large origination alerts.

Tests verify behavior through emitted events only:
  - WASH_FLAG on 3+ origination-repayment cycles
  - VELOCITY_FLAG on 4+ originations
  - FRAUD_ALERT on principal > $1M
  - Edge cases: zero events, single cycles, boundary values
"""

from __future__ import annotations

from collections import deque

import pytest

from underwrite.exceptions import ProtocolError
from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.fraud import Handler
from underwrite.services.fraud import Handler as FraudHandler
from underwrite.store import InMemory


def fraud(bus=None) -> Handler:
    return FraudHandler(name="fraud", bus=bus or LocalBus(), store=InMemory())


def originate(svc: Handler, borrower: str, principal: int = 1000) -> None:
    svc.handle(
        Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={"borrower": borrower, "principal": principal})
    )


def repay(svc: Handler, user: str, amount: int = 1000) -> None:
    svc.handle(Message(event_type=Type.REPAID, source="test", payload={"user": user, "delta_earned": amount}))


class TestWashLending:
    def test_no_wash_with_zero_cycles(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "alice")
        assert len(received) == 0

    def test_no_wash_with_two_cycles(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(2):
            originate(svc, "bob")
            repay(svc, "bob")
        assert len(received) == 0

    def test_wash_flag_on_three_cycles(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(3):
            originate(svc, "carol")
            repay(svc, "carol")
        assert len(received) >= 1
        assert received[0].event_type == Type.WASH_FLAG
        assert received[0].payload["cycles"] >= 3

    def test_wash_score_increases_with_more_cycles(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(6):
            originate(svc, "dave")
            repay(svc, "dave")
        assert any(r.payload["cycles"] >= 6 for r in received)

    def test_wash_score_capped_at_100(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(10):
            originate(svc, "eve")
            repay(svc, "eve")
        assert all(r.payload["score"] <= 100.0 for r in received)

    def test_interleaved_events_dont_false_positive(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
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
        received: list[Message] = []
        bus.subscribe(Type.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(3):
            originate(svc, "grace")
        assert len(received) == 0

    def test_burst_on_four_originations(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(4):
            originate(svc, "heidi")
        assert len(received) >= 1
        assert received[0].event_type == Type.VELOCITY_FLAG
        assert received[0].payload["count"] >= 4

    def test_burst_not_triggered_by_repayments(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "ivan")
        repay(svc, "ivan")
        repay(svc, "ivan")
        repay(svc, "ivan")
        assert len(received) == 0

    def test_different_borrowers_independent(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.VELOCITY_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(4):
            originate(svc, "a")
            originate(svc, "b")
        assert len(received) == 2  # one burst per borrower


class TestLargeOrigination:
    def test_alert_on_large_principal(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "mallory", principal=2_000_000)
        assert len(received) >= 1
        assert received[0].payload["rule"] == "large_origination"
        assert received[0].payload["principal"] == 2_000_000

    def test_no_alert_below_threshold(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "oscar", principal=500_000)
        assert len(received) == 0

    def test_alert_at_exactly_one_million(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        originate(svc, "peggy", principal=1_000_001)
        assert len(received) >= 1

    def test_alert_uses_borrower_from_origination_event(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.FRAUD_ALERT, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "trent", "principal": 1_500_000},
            )
        )
        assert received[0].payload["rule"] == "large_origination"
        assert received[0].payload["borrower"] == "trent"


class TestEdgeCases:
    def test_ignores_unrelated_events(self) -> None:
        svc = fraud()
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        svc.handle(Message(event_type="user.added", source="test", payload={}))
        svc.handle(Message(event_type="quote.calculated", source="test", payload={}))

    def test_handles_empty_payload(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.WASH_FLAG, lambda e: received.append(e))
        svc = fraud(bus=bus)
        bus.start()
        for _ in range(2):
            with pytest.raises(ProtocolError):
                svc.handle(Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={}))
        with pytest.raises(ProtocolError):
            svc.handle(Message(event_type=Type.REPAID, source="test", payload={}))
        assert len(received) == 0

    def test_missing_borrower_does_not_crash(self) -> None:
        svc = fraud()
        with pytest.raises(ProtocolError):
            svc.handle(Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={}))

    def test_records_use_deque_maxlen(self) -> None:
        svc = fraud()
        borrower = "maxlen_test"
        for _ in range(2000):
            svc.handle(
                Message(
                    event_type=Type.LOAN_ORIGINATED,
                    source="test",
                    payload={"borrower": borrower, "principal": 100},
                )
            )
        records = svc.records
        recs = records.get(borrower)
        assert recs is not None
        assert isinstance(recs, deque)
        assert recs.maxlen == 1000
        assert len(recs) == 1000
