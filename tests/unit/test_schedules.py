"""Unit tests for schedule generation and versioning."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ulu.servicing.schedules import (
    ScheduleType,
    ScheduleVersion,
    ScheduleVersionManager,
    generate_schedule,
    generate_schedule_decimal,
    versioned_schedule,
)


class TestGenerateSchedule:
    def test_amortizing_schedule(self) -> None:
        sched = generate_schedule(1000.0, 3, 0.12, ScheduleType.AMORTIZING)
        assert len(sched) == 3
        total_principal = sum(i.principal_due for i in sched)
        assert total_principal == pytest.approx(1000.0, rel=1e-6)

    def test_bullet_schedule(self) -> None:
        sched = generate_schedule(1000.0, 3, 0.12, ScheduleType.BULLET)
        assert len(sched) == 3
        assert sched[-1].principal_due == pytest.approx(1000.0)
        assert sched[0].principal_due == pytest.approx(0.0)

    def test_interest_only_schedule(self) -> None:
        sched = generate_schedule(1000.0, 3, 0.12, ScheduleType.INTEREST_ONLY)
        assert len(sched) == 3
        assert all(i.principal_due == pytest.approx(0.0) for i in sched)

    def test_zero_rate_amortizing(self) -> None:
        sched = generate_schedule(900.0, 3, 0.0, ScheduleType.AMORTIZING)
        assert all(i.interest_due == pytest.approx(0.0) for i in sched)
        assert sum(i.principal_due for i in sched) == pytest.approx(900.0)

    def test_invalid_principal(self) -> None:
        with pytest.raises(ValueError, match="principal"):
            generate_schedule(-1.0, 3, 0.12, ScheduleType.BULLET)

    def test_invalid_term(self) -> None:
        with pytest.raises(ValueError, match="term"):
            generate_schedule(1000.0, 0, 0.12, ScheduleType.BULLET)


class TestVersionedSchedule:
    def test_versioned_schedule_creation(self) -> None:
        vs = versioned_schedule(
            principal=1000.0,
            term=3,
            annual_rate=0.12,
            schedule_type=ScheduleType.AMORTIZING,
            version=1,
            change_reason="origination",
        )
        assert isinstance(vs, ScheduleVersion)
        assert vs.version == 1
        assert vs.change_reason == "origination"
        assert len(vs.installments) == 3


class TestScheduleVersionManager:
    def test_add_and_latest(self) -> None:
        mgr = ScheduleVersionManager()
        vs = versioned_schedule(1000.0, 3, 0.12, ScheduleType.AMORTIZING)
        mgr.add_version(vs)
        assert mgr.latest() == vs

    def test_history_order(self) -> None:
        mgr = ScheduleVersionManager()
        mgr.add_version(versioned_schedule(1000.0, 3, 0.12, ScheduleType.AMORTIZING, version=1))
        mgr.add_version(versioned_schedule(800.0, 2, 0.10, ScheduleType.AMORTIZING, version=2))
        history = mgr.history()
        assert len(history) == 2
        assert history[0].version == 1
        assert history[1].version == 2

    def test_restructure_increments_version(self) -> None:
        mgr = ScheduleVersionManager()
        mgr.add_version(versioned_schedule(1000.0, 3, 0.12, ScheduleType.AMORTIZING, version=1))
        new = mgr.restructure(
            principal=800.0,
            term=2,
            annual_rate=0.10,
            schedule_type=ScheduleType.AMORTIZING,
            reason="tenor_extension",
        )
        assert new.version == 2
        assert new.change_reason == "tenor_extension"
        assert mgr.latest() == new

    def test_empty_manager(self) -> None:
        mgr = ScheduleVersionManager()
        assert mgr.latest() is None
        assert mgr.history() == []


class TestGenerateScheduleDecimal:
    def test_decimal_amortizing_matches_float(self) -> None:
        float_sched = generate_schedule(1000.0, 3, 0.12, ScheduleType.AMORTIZING)
        dec_sched = generate_schedule_decimal(Decimal("1000"), 3, Decimal("0.12"), ScheduleType.AMORTIZING)
        assert len(float_sched) == len(dec_sched)
        for f, d in zip(float_sched, dec_sched, strict=True):
            assert f.sequence == d.sequence
            assert f.principal_due == pytest.approx(d.principal_due, rel=1e-6)
            assert f.interest_due == pytest.approx(d.interest_due, rel=1e-6)
            assert f.total_due == pytest.approx(d.total_due, rel=1e-6)

    def test_decimal_bullet(self) -> None:
        sched = generate_schedule_decimal(Decimal("1000"), 3, Decimal("0.12"), ScheduleType.BULLET)
        assert len(sched) == 3
        assert sched[-1].principal_due == pytest.approx(1000.0)

    def test_decimal_zero_rate(self) -> None:
        sched = generate_schedule_decimal(Decimal("900"), 3, Decimal("0"), ScheduleType.AMORTIZING)
        total_principal = sum(i.principal_due for i in sched)
        assert total_principal == pytest.approx(900.0)

    def test_decimal_invalid_principal(self) -> None:
        with pytest.raises(ValueError, match="principal"):
            generate_schedule_decimal(Decimal("-1"), 3, Decimal("0.12"), ScheduleType.BULLET)
