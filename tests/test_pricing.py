# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Handler — RBI-compliant rate and fee computation."""

from __future__ import annotations

import pytest

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.pricing import (
    HOME_LOAN_CAP,
    MICRO_LOAN_CAP,
    PERSONAL_LOAN_CAP,
    Handler,
    compute_rate_cap,
)
from underwrite.services.pricing import (
    Handler as PricingHandler,
)
from underwrite.store import InMemory


def svc(**kwargs) -> Handler:
    kwargs.setdefault("bus", LocalBus())
    kwargs.setdefault("store", InMemory())
    return PricingHandler(name="pricing", **kwargs)


def request(svc, bus, **kw) -> None:
    bus.start()
    svc.handle(Message(event_type="pricing.request", source="test", payload=kw))


class TestRateCap:
    def test_home_loan_cap(self) -> None:
        assert compute_rate_cap(5000000, "home") == HOME_LOAN_CAP

    def test_personal_loan_cap(self) -> None:
        assert compute_rate_cap(100000, "personal") == PERSONAL_LOAN_CAP

    def test_micro_loan_cap_applied_for_small_loans(self) -> None:
        cap = compute_rate_cap(10000, "personal")
        assert cap == MICRO_LOAN_CAP

    def test_micro_loan_cap_overrides_home_cap_for_small_loans(self) -> None:
        cap = compute_rate_cap(10000, "home")
        assert cap == MICRO_LOAN_CAP

    def test_large_loan_uses_product_cap(self) -> None:
        cap = compute_rate_cap(100000, "home")
        assert cap == HOME_LOAN_CAP

    def test_default_loan_cap(self) -> None:
        cap = compute_rate_cap(500000, "unknown_type")
        assert cap == 0.30


class TestPricing:
    def test_computes_base_rate_for_low_risk(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="alice", principal=10000, default_probability=0.02)
        assert received[0].payload["interest_rate"] == 0.09
        assert received[0].payload["origination_fee"] == 100.0

    def test_higher_risk_higher_rate(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="bob", principal=10000, default_probability=0.20)
        assert received[0].payload["interest_rate"] > 0.09

    def test_rate_capped_at_all_in_cost_limit(self) -> None:
        """Over-cap requests are now rejected (RBI rule) rather than silently clamped."""
        from underwrite.exceptions import ProtocolError

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        with pytest.raises(ProtocolError, match="exceeds personal cap"):
            request(
                svc(bus=bus),
                bus,
                borrower="high_risk",
                principal=100000,
                default_probability=0.80,
                loan_type="personal",
            )
        assert received == []

    def test_micro_loan_rate_capped_by_principal(self) -> None:
        """Small principal → micro cap; over-cap request rejected."""
        from underwrite.exceptions import ProtocolError

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        with pytest.raises(ProtocolError, match="exceeds personal cap"):
            request(
                svc(bus=bus),
                bus,
                borrower="micro",
                principal=5000,
                default_probability=0.80,
                loan_type="personal",
            )
        assert received == []

    def test_origination_fee_is_one_percent_by_default(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="carol", principal=50000, default_probability=0.05)
        assert received[0].payload["origination_fee"] == 500.0

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        svc_inst = svc(bus=bus)
        bus.start()
        svc_inst.handle(Message(event_type="seed.added", source="test", payload={}))
        assert len(received) == 0

    def test_missing_dp_defaults(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="dave", principal=10000)
        assert received[0].payload["risk_premium"] == 0.01

    def test_emi_computed_in_result(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="emi_test", principal=100000, default_probability=0.02, tenure_months=12)
        assert received[0].payload["emi_amount"] > 0
        assert received[0].payload["tenure_months"] == 12
        assert received[0].payload["total_interest_payable"] > 0
        assert received[0].payload["total_repayment"] > 100000

    def test_apr_included_in_result(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="apr_test", principal=100000, default_probability=0.02, tenure_months=12)
        assert received[0].payload["annual_percentage_rate"] > 0
        assert received[0].payload["annual_percentage_rate"] >= received[0].payload["interest_rate"]

    def test_gst_on_fees_included(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="gst_test", principal=100000, default_probability=0.02)
        assert received[0].payload["gst_on_fees"] > 0
        assert received[0].payload["total_upfront_fees"] > 0

    def test_penal_interest_computed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe("pricing.penal_interest_computed", lambda e: received.append(e))
        svc_inst = svc(bus=bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type="pricing.penal_interest",
                source="test",
                payload={
                    "borrower": "penal_test",
                    "overdue_amount": 10000,
                    "overdue_days": 30,
                },
            )
        )
        assert len(received) == 1
        assert received[0].payload["penal_interest_amount"] > 0
        assert received[0].payload["penal_interest_rate"] == 0.24

    def test_foreclosure_computed(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe("pricing.foreclosure_computed", lambda e: received.append(e))
        svc_inst = svc(bus=bus)
        bus.start()
        svc_inst.handle(
            Message(
                event_type="pricing.foreclosure",
                source="test",
                payload={
                    "borrower": "foreclose_test",
                    "outstanding_principal": 80000,
                    "loan_type": "personal",
                },
            )
        )
        assert len(received) == 1
        assert received[0].payload["foreclosure_charge"] == 4000.0
        assert received[0].payload["total_due"] == 84000.0

    def test_credit_score_and_income_included(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(
            svc(bus=bus),
            bus,
            borrower="full_profile",
            principal=100000,
            default_probability=0.02,
            credit_score=750,
            annual_income=600000,
        )
        p = received[0].payload
        assert p["credit_score"] == 750
        assert p["annual_income"] == 600000
        assert "debt_to_income_ratio" in p

    def test_home_loan_lower_origination_fee(self) -> None:
        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        request(svc(bus=bus), bus, borrower="home_buyer", principal=5000000, default_probability=0.02, loan_type="home")
        assert received[0].payload["origination_fee_pct"] == 0.005

    def test_rate_cap_applied_flag(self) -> None:
        """Over-cap requests are now rejected outright, so the flag is no longer used."""
        from underwrite.exceptions import ProtocolError

        bus = LocalBus()
        received: list = []
        bus.subscribe(Type.PRICING_COMPUTED, lambda e: received.append(e))
        with pytest.raises(ProtocolError, match="exceeds personal cap"):
            request(
                svc(bus=bus),
                bus,
                borrower="capped",
                principal=100000,
                default_probability=0.60,
                loan_type="personal",
            )
