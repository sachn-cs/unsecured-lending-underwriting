"""Tests for NPAService — RBI-mandated asset classification and DLG triggers.

Tests verify behavior through:
  - Emitted NPA_BUCKET_CHANGED and DLG_TRIGGERED events
  - Edge cases: unknown borrower, DLG invoked only once, bucket boundaries
"""

from __future__ import annotations

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.npa.service import NPAService


def npa(bus=None) -> NPAService:
    return NPAService(service_id="npa", bus=bus)


class TestBucketClassification:

    def test_standard_0_days(self) -> None:
        assert NPAService.classify_overdue_days(0) == "standard"

    def test_standard_30_days(self) -> None:
        assert NPAService.classify_overdue_days(30) == "standard"

    def test_standard_at_boundary_90(self) -> None:
        assert NPAService.classify_overdue_days(90) == "standard"

    def test_substandard_91_days(self) -> None:
        assert NPAService.classify_overdue_days(91) == "substandard"

    def test_substandard_180_days(self) -> None:
        assert NPAService.classify_overdue_days(180) == "substandard"

    def test_doubtful_181_days(self) -> None:
        assert NPAService.classify_overdue_days(181) == "doubtful"

    def test_doubtful_360_days(self) -> None:
        assert NPAService.classify_overdue_days(360) == "doubtful"

    def test_loss_361_days(self) -> None:
        assert NPAService.classify_overdue_days(361) == "loss"

    def test_loss_over_1000_days(self) -> None:
        assert NPAService.classify_overdue_days(1000) == "loss"

    def test_negative_days_standard(self) -> None:
        assert NPAService.classify_overdue_days(-5) == "standard"


class TestLoanTracking:

    def test_creates_account_on_origination(self) -> None:
        bus = LocalBus()
        bucket_events: list[Event] = []
        bus.subscribe(EventType.NPA_BUCKET_CHANGED,
                      lambda e: bucket_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "alice"}))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "alice",
                      "principal": 50000
                  }))
        assert len(bucket_events) == 1
        assert bucket_events[0].payload["borrower"] == "alice"
        assert bucket_events[0].payload["bucket"] == "standard"

    def test_dlg_triggered_when_overdue_past_threshold(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "bob"}))
        svc.mark_overdue("bob", 150)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "bob",
                      "principal": 30000
                  }))
        assert len(dlg) == 1
        assert dlg[0].payload["recovery_amount"] == 30000.0

    def test_no_dlg_below_overdue_threshold(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "carol"}))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "carol",
                      "principal": 10000
                  }))
        assert len(dlg) == 0

    def test_dlg_only_invoked_once(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "dave"}))
        svc.mark_overdue("dave", 150)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "dave",
                      "principal": 20000
                  }))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "dave",
                      "principal": 20000
                  }))
        assert len(dlg) == 1

    def test_default_unknown_borrower_does_not_crash(self) -> None:
        svc = npa()
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={"borrower": "ghost"}))

    def test_ignores_unrelated_events(self) -> None:
        bus = LocalBus()
        bucket: list[Event] = []
        bus.subscribe(EventType.NPA_BUCKET_CHANGED, lambda e: bucket.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(Event(event_type="seed.added", source="test", payload={}))
        svc.handle(Event(event_type="user.added", source="test", payload={}))
        assert len(bucket) == 0

    def test_multiple_borrowers_independent(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "x"}))
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={"borrower": "y"}))
        svc.mark_overdue("x", 150)
        svc.mark_overdue("y", 50)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "x",
                      "principal": 5000
                  }))
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED,
                  source="test",
                  payload={
                      "borrower": "y",
                      "principal": 5000
                  }))
        assert len(dlg) == 1  # only x exceeds threshold
        assert dlg[0].payload["loan_id"] == "x"
