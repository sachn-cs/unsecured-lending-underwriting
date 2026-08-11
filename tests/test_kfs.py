# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for KFS service — Key Fact Statement generation."""

from __future__ import annotations

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.kfs import Handler
from underwrite.services.kfs import Handler as KfsHandler
from underwrite.store import Sqlite


def svc(bus=None) -> Handler:
    return KfsHandler(name="kfs", bus=bus or LocalBus(), store=Sqlite(":memory:"))


class TestKfsService:
    def test_generate_kfs_missing_loan_id_ignored(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type=Type.KFS_GENERATE, source="test", payload={}))
        assert len(received) == 0

    def test_generate_kfs_basic(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.KFS_GENERATE,
                source="test",
                payload={
                    "loan_id": "L1",
                    "borrower": "alice",
                    "principal": 100000,
                    "annual_rate": 12,
                    "tenure_months": 12,
                },
            )
        )
        assert len(received) == 1
        kfs = received[0].payload
        assert kfs["loan_id"] == "L1"
        assert kfs["borrower"] == "alice"
        assert kfs["loan_amount"] == 100000.0
        assert kfs["annual_interest_rate"] == 12.0
        assert kfs["tenure_months"] == 12
        assert kfs["emi_amount"] > 0
        assert kfs["total_interest_payable"] > 0
        assert kfs["total_repayment"] > 100000.0
        assert kfs["cooling_off_days"] == 3

    def test_generate_kfs_with_fees(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.KFS_GENERATE,
                source="test",
                payload={
                    "loan_id": "L2",
                    "borrower": "bob",
                    "principal": 100000,
                    "annual_rate": 12,
                    "tenure_months": 12,
                    "fees": [{"type": "processing", "amount": 500}, {"type": "documentation", "amount": 200}],
                },
            )
        )
        assert len(received) == 1
        kfs = received[0].payload
        assert len(kfs["fees_and_charges"]) == 2
        assert kfs["total_fees"] == 700.0
        assert kfs["annual_percentage_rate"] > 12.0

    def test_generate_kfs_with_start_date(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.KFS_GENERATE,
                source="test",
                payload={
                    "loan_id": "L3",
                    "borrower": "carol",
                    "principal": 50000,
                    "annual_rate": 10,
                    "tenure_months": 6,
                    "start_date": "2025-01-15",
                },
            )
        )
        assert len(received) == 1
        kfs = received[0].payload
        assert "start_date" in kfs
        assert kfs["start_date"] == "2025-01-15"

    def test_generate_kfs_zero_rate_handling(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.KFS_GENERATE,
                source="test",
                payload={
                    "loan_id": "L4",
                    "borrower": "dave",
                    "principal": 10000,
                    "annual_rate": 0,
                    "tenure_months": 6,
                },
            )
        )
        # Should not generate KFS (invalid rate)
        assert len(received) == 0

    def test_generate_kfs_zero_principal(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type=Type.KFS_GENERATE,
                source="test",
                payload={
                    "loan_id": "L5",
                    "borrower": "eve",
                    "principal": 0,
                    "annual_rate": 12,
                    "tenure_months": 12,
                },
            )
        )
        assert len(received) == 0

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.KFS_GENERATED, lambda e: received.append(e))
        svc_inst = svc(bus)
        bus.start()
        svc_inst.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0
