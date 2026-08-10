"""Tests for RiskHandler — ML scoring and early-warning signals.

Tests verify behavior through emitted events:
  - RISK_EARLY_WARNING on default_probability > 0.3
  - Edge cases: boundary values, missing fields, non-loan events
"""

from __future__ import annotations

import pytest

from underwrite.exceptions import ProtocolError
from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.risk.handler import RiskHandler
from underwrite.store import MemoryStore


def risk(bus=None) -> RiskHandler:
    return RiskHandler(service_id="risk", bus=bus or LocalBus(), store=MemoryStore())


class TestEarlyWarning:
    def test_warning_on_high_default_probability(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "alice", "default_probability": 0.45, "principal": 10000},
            )
        )
        assert len(received) == 1
        assert received[0].payload["borrower"] == "alice"
        assert received[0].payload["default_probability"] == 0.45

    def test_no_warning_on_low_default_probability(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "bob", "default_probability": 0.05, "principal": 10000},
            )
        )
        assert len(received) == 0

    def test_no_warning_at_exactly_thirty_percent(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "carol", "default_probability": 0.30, "principal": 10000},
            )
        )
        assert len(received) == 0

    def test_warning_just_above_thirty_percent(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "dave", "default_probability": 0.3001, "principal": 10000},
            )
        )
        assert len(received) == 1

    def test_warning_at_one_hundred_percent(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "eve", "default_probability": 1.0, "principal": 10000},
            )
        )
        assert len(received) == 1

    def test_missing_default_probability_no_warning(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={"borrower": "frank", "principal": 10000})
        )
        assert len(received) == 0

    def test_string_default_probability_parsed(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "grace", "default_probability": "0.50", "principal": 10000},
            )
        )
        assert len(received) == 1


class TestEdgeCases:
    def test_no_model_no_crash(self) -> None:
        svc = risk()
        svc.handle(
            Message(
                event_type=Type.LOAN_ORIGINATED,
                source="test",
                payload={"borrower": "heidi", "default_probability": 0.02, "principal": 10000},
            )
        )

    def test_ignores_non_loan_events(self) -> None:
        bus = LocalBus()
        received: list[Message] = []
        bus.subscribe(Type.RISK_EARLY_WARNING, lambda e: received.append(e))
        svc = risk(bus=bus)
        bus.start()
        svc.handle(Message(event_type="seed.added", source="test", payload={}))
        svc.handle(Message(event_type=Type.REPAID, source="test", payload={}))
        svc.handle(Message(event_type=Type.DEFAULT_OCCURRED, source="test", payload={}))
        assert len(received) == 0

    def test_empty_payload_no_crash(self) -> None:
        svc = risk()
        with pytest.raises(ProtocolError):
            svc.handle(Message(event_type=Type.LOAN_ORIGINATED, source="test", payload={}))
