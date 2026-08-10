"""Property-based tests for validate.py and __amortization__.py using hypothesis.

AGENTS.md § Testing: "Property-Based Testing — Where appropriate,
verify general properties rather than individual examples."

Validators and the amortization engine are prime property-test
targets: they have invariants (positive inputs pass, negative
inputs raise) that hold over the entire input domain.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from underwrite.amortization import (
    calculate_emi,
    generate_schedule,
    project_outstanding,
)
from underwrite.exceptions import ProtocolError
from underwrite.services.pricing.handler import compute_rate_cap
from underwrite.validate import PayloadValidator

finite_float = st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False)
positive_float = st.floats(min_value=1e-6, max_value=1e9, allow_nan=False, allow_infinity=False)
non_negative_float = st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False)
negative_float = st.floats(min_value=-1e9, max_value=-1e-6, allow_nan=False, allow_infinity=False)
non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7E),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")


class TestRequirePositive:
    @given(value=positive_float)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_positive_passes(self, value: float) -> None:
        result = PayloadValidator.require_positive(value, "v")
        assert result == value
        assert result > 0

    @given(value=negative_float)
    @settings(max_examples=30)
    def test_non_positive_raises(self, value: float) -> None:
        with pytest.raises(ProtocolError, match="must be positive"):
            PayloadValidator.require_positive(value, "v")


class TestRequireNonNegative:
    @given(value=non_negative_float)
    @settings(max_examples=50)
    def test_non_negative_passes(self, value: float) -> None:
        result = PayloadValidator.require_non_negative(value, "v")
        assert result == value
        assert result >= 0

    @given(value=negative_float)
    @settings(max_examples=30)
    def test_negative_raises(self, value: float) -> None:
        with pytest.raises(ProtocolError, match="must be non-negative"):
            PayloadValidator.require_non_negative(value, "v")


class TestRequireFinite:
    @given(value=finite_float)
    @settings(max_examples=50)
    def test_finite_passes(self, value: float) -> None:
        assert PayloadValidator.require_finite(value, "v") == value

    @given(value=st.just(float("inf")))
    @settings(max_examples=10)
    def test_infinity_raises(self, value: float) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_finite(value, "v")

    @given(value=st.just(float("nan")))
    @settings(max_examples=10)
    def test_nan_raises(self, value: float) -> None:
        with pytest.raises(ProtocolError, match="must be finite"):
            PayloadValidator.require_finite(value, "v")


class TestRequireInRange:
    @given(
        lo=st.floats(min_value=-100.0, max_value=0.0, allow_nan=False),
        hi=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_midpoint_in_range_passes(self, lo: float, hi: float) -> None:
        assume(hi > lo)
        midpoint = (lo + hi) / 2.0
        assert PayloadValidator.require_in_range(midpoint, lo, hi, "v") == midpoint

    @given(
        lo=st.floats(min_value=-100.0, max_value=0.0, allow_nan=False),
        hi=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
        delta=st.floats(min_value=0.01, max_value=10.0),
    )
    @settings(max_examples=30)
    def test_above_range_raises(self, lo: float, hi: float, delta: float) -> None:
        assume(hi > lo)
        with pytest.raises(ProtocolError, match=r"must be in \["):
            PayloadValidator.require_in_range(hi + delta, lo, hi, "v")


class TestAmortizationInvariants:
    @given(
        principal=st.decimals(min_value=Decimal("10000"), max_value=Decimal("1000000"), places=2),
        annual_rate=st.decimals(min_value=Decimal("0.05"), max_value=Decimal("0.30"), places=4),
        tenure=st.integers(min_value=6, max_value=120),
    )
    @settings(max_examples=20)
    def test_first_entry_reduces_principal(self, principal: Decimal, annual_rate: Decimal, tenure: int) -> None:
        schedule = generate_schedule(principal, annual_rate, tenure)
        assert len(schedule.entries) == tenure
        first = schedule.entries[0]
        assert first.outstanding_principal < principal
        assert first.principal_component > Decimal("0")
        assert first.interest_component > Decimal("0")

    @given(
        principal=st.decimals(min_value=Decimal("10000"), max_value=Decimal("1000000"), places=2),
        annual_rate=st.decimals(min_value=Decimal("0.05"), max_value=Decimal("0.30"), places=4),
        tenure=st.integers(min_value=6, max_value=120),
    )
    @settings(max_examples=20)
    def test_last_entry_zeros_outstanding(self, principal: Decimal, annual_rate: Decimal, tenure: int) -> None:
        schedule = generate_schedule(principal, annual_rate, tenure)
        last = schedule.entries[-1]
        assert last.outstanding_principal <= principal * Decimal("0.0001")

    @given(
        principal=st.decimals(min_value=Decimal("100000"), max_value=Decimal("1000000"), places=2),
        annual_rate_low=st.decimals(min_value=Decimal("0.05"), max_value=Decimal("0.10"), places=4),
        annual_rate_high=st.decimals(min_value=Decimal("0.20"), max_value=Decimal("0.30"), places=4),
        tenure=st.integers(min_value=12, max_value=60),
    )
    @settings(max_examples=15)
    def test_higher_rate_yields_higher_emi(
        self,
        principal: Decimal,
        annual_rate_low: Decimal,
        annual_rate_high: Decimal,
        tenure: int,
    ) -> None:
        assume(annual_rate_high > annual_rate_low)
        emi_low = calculate_emi(principal, annual_rate_low / Decimal("12"), tenure)
        emi_high = calculate_emi(principal, annual_rate_high / Decimal("12"), tenure)
        assert emi_high > emi_low


class TestRateCap:
    @given(principal=st.floats(min_value=1.0, max_value=1e8, allow_nan=False))
    @settings(max_examples=30)
    def test_rate_cap_strictly_positive(self, principal: float) -> None:
        for loan_type in ("home", "gold", "personal", "micro"):
            cap = compute_rate_cap(principal, loan_type)
            assert cap > 0

    @given(principal=st.floats(min_value=1.0, max_value=1e8, allow_nan=False))
    @settings(max_examples=30)
    def test_home_cap_le_personal_cap(self, principal: float) -> None:
        home_cap = compute_rate_cap(principal, "home")
        personal_cap = compute_rate_cap(principal, "personal")
        assert home_cap <= personal_cap


class TestOutstandingMonotone:
    @given(
        principal=st.decimals(min_value=Decimal("100000"), max_value=Decimal("1000000"), places=2),
        annual_rate=st.decimals(min_value=Decimal("0.10"), max_value=Decimal("0.20"), places=4),
        tenure=st.integers(min_value=12, max_value=60),
    )
    @settings(max_examples=15)
    def test_project_outstanding_idempotent_on_no_payments(
        self,
        principal: Decimal,
        annual_rate: Decimal,
        tenure: int,
    ) -> None:
        b1 = project_outstanding(principal, annual_rate, tenure, [])
        b2 = project_outstanding(principal, annual_rate, tenure, [])
        assert b1.principal_outstanding == b2.principal_outstanding
        assert b1.accrued_interest == b2.accrued_interest
        assert b1.days_overdue == b2.days_overdue
