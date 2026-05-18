"""Unit tests for NPA modules."""

from __future__ import annotations

from ulu.npa.aging import NpaAgingTracker, NpaBucket
from ulu.npa.scheduler import NpaScheduler
from ulu.npa.triggers import DlgTriggerService


class TestNpaAgingTracker:
    def test_standard_bucket(self) -> None:
        tracker = NpaAgingTracker()
        assert tracker.bucket_for_days(0) == NpaBucket.STANDARD
        assert tracker.bucket_for_days(-5) == NpaBucket.STANDARD
        assert tracker.bucket_for_days(30) == NpaBucket.STANDARD
        assert tracker.bucket_for_days(89) == NpaBucket.STANDARD
        assert tracker.bucket_for_days(90) == NpaBucket.STANDARD

    def test_substandard_bucket(self) -> None:
        tracker = NpaAgingTracker()
        assert tracker.bucket_for_days(91) == NpaBucket.SUBSTANDARD
        assert tracker.bucket_for_days(180) == NpaBucket.SUBSTANDARD

    def test_doubtful_bucket(self) -> None:
        tracker = NpaAgingTracker()
        assert tracker.bucket_for_days(181) == NpaBucket.DOUBTFUL
        assert tracker.bucket_for_days(360) == NpaBucket.DOUBTFUL

    def test_loss_bucket(self) -> None:
        tracker = NpaAgingTracker()
        assert tracker.bucket_for_days(361) == NpaBucket.LOSS
        assert tracker.bucket_for_days(500) == NpaBucket.LOSS

    def test_dlg_trigger(self) -> None:
        tracker = NpaAgingTracker(trigger_days=120)
        assert tracker.is_dlg_trigger(119) is False
        assert tracker.is_dlg_trigger(120) is True
        assert tracker.is_dlg_trigger(200) is True


class TestNpaScheduler:
    def test_evaluate(self) -> None:
        scheduler = NpaScheduler()
        days, bucket, dlg = scheduler.evaluate(119)
        assert days == 120
        assert bucket == NpaBucket.SUBSTANDARD
        assert dlg is True


class TestDlgTriggerService:
    def test_should_invoke(self) -> None:
        svc = DlgTriggerService()
        assert svc.should_invoke(120, already_invoked=False) is True
        assert svc.should_invoke(120, already_invoked=True) is False
        assert svc.should_invoke(119, already_invoked=False) is False

    def test_invoke(self) -> None:
        svc = DlgTriggerService()
        event = svc.invoke("l1", 50.0)
        assert event.loan_id == "l1"
        assert event.recovery_amount == 50.0
        assert event.invoked_at is not None
