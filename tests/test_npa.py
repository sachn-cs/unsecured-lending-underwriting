"""Tests for NPAHandler — RBI-mandated asset classification and DLG triggers.

Tests verify behavior through:
  - Emitted NPA_BUCKET_CHANGED and DLG_TRIGGERED events
  - Edge cases: unknown borrower, DLG invoked only once, bucket boundaries
  - SMA classification (SMA-0, SMA-1, SMA-2)
  - Provisioning computation per RBI bucket
  - Income recognition suspension for NPA accounts
"""

from __future__ import annotations
from underwrite.__store__ import MemoryStore

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.services.npa.handler import NPAHandler


def npa(bus=None) -> NPAHandler:
    return NPAHandler(service_id="npa", bus=bus or LocalBus(), store=MemoryStore())


class TestBucketClassification:
    def test_standard_0_days(self) -> None:
        assert NPAHandler.classify_overdue_days(0) == "standard"

    def test_standard_30_days(self) -> None:
        assert NPAHandler.classify_overdue_days(30) == "standard"

    def test_standard_89_days(self) -> None:
        assert NPAHandler.classify_overdue_days(89) == "standard"

    def test_npa_at_boundary_90(self) -> None:
        """RBI: an asset becomes NPA on day 90+ past due."""
        assert NPAHandler.classify_overdue_days(90) == "substandard"

    def test_substandard_91_days(self) -> None:
        assert NPAHandler.classify_overdue_days(91) == "substandard"

    def test_substandard_179_days(self) -> None:
        assert NPAHandler.classify_overdue_days(179) == "substandard"

    def test_doubtful_180_days(self) -> None:
        assert NPAHandler.classify_overdue_days(180) == "doubtful"

    def test_doubtful_181_days(self) -> None:
        assert NPAHandler.classify_overdue_days(181) == "doubtful"

    def test_doubtful_359_days(self) -> None:
        assert NPAHandler.classify_overdue_days(359) == "doubtful"

    def test_loss_360_days(self) -> None:
        assert NPAHandler.classify_overdue_days(360) == "loss"

    def test_loss_over_1000_days(self) -> None:
        assert NPAHandler.classify_overdue_days(1000) == "loss"

    def test_negative_days_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="non-negative"):
            NPAHandler.classify_overdue_days(-5)


class TestLoanTracking:
    def test_creates_account_on_origination(self) -> None:
        bus = LocalBus()
        bucket_events: list[Event] = []
        bus.subscribe(EventType.NPA_BUCKET_CHANGED, lambda e: bucket_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "alice"}))
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "alice", "principal": 50000}
            )
        )
        assert len(bucket_events) == 1
        assert bucket_events[0].payload["borrower"] == "alice"
        assert bucket_events[0].payload["bucket"] == "standard"

    def test_dlg_triggered_when_overdue_past_threshold(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "bob"}))
        svc.mark_overdue("bob", 150)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "bob", "principal": 30000})
        )
        assert len(dlg) == 1
        assert dlg[0].payload["recovery_amount"] == 30000.0

    def test_no_dlg_below_overdue_threshold(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "carol"}))
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "carol", "principal": 10000}
            )
        )
        assert len(dlg) == 0

    def test_dlg_only_invoked_once(self) -> None:
        bus = LocalBus()
        dlg: list[Event] = []
        bus.subscribe(EventType.DLG_TRIGGERED, lambda e: dlg.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "dave"}))
        svc.mark_overdue("dave", 150)
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "dave", "principal": 20000}
            )
        )
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "dave", "principal": 20000}
            )
        )
        assert len(dlg) == 1

    def test_default_unknown_borrower_does_not_crash(self) -> None:
        svc = npa()
        svc.handle(Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "ghost"}))

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
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "x"}))
        svc.handle(Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "y"}))
        svc.mark_overdue("x", 150)
        svc.mark_overdue("y", 50)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "x", "principal": 5000})
        )
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "y", "principal": 5000})
        )
        assert len(dlg) == 1  # only x exceeds threshold
        assert dlg[0].payload["loan_id"] == "x"


class TestSmaClassification:
    def test_sma_0_at_1_day(self) -> None:
        assert NPAHandler.sma_classify(1) == "sma_0"

    def test_sma_0_at_30_days(self) -> None:
        assert NPAHandler.sma_classify(30) == "sma_0"

    def test_sma_1_at_31_days(self) -> None:
        assert NPAHandler.sma_classify(31) == "sma_1"

    def test_sma_1_at_60_days(self) -> None:
        assert NPAHandler.sma_classify(60) == "sma_1"

    def test_sma_2_at_61_days(self) -> None:
        assert NPAHandler.sma_classify(61) == "sma_2"

    def test_sma_2_at_90_days(self) -> None:
        assert NPAHandler.sma_classify(90) == "sma_2"

    def test_sma_empty_for_0_days(self) -> None:
        assert NPAHandler.sma_classify(0) == ""

    def test_sma_empty_for_negative_days(self) -> None:
        assert NPAHandler.sma_classify(-1) == ""

    def test_sma_empty_beyond_90_days(self) -> None:
        assert NPAHandler.sma_classify(91) == ""


class TestProvisioningAndIncomeSuspension:
    def test_provisioning_amount_computed(self) -> None:
        bus = LocalBus()
        prov_events: list[Event] = []
        bus.subscribe(EventType.PROVISIONING_COMPUTED, lambda e: prov_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "p1", "principal": 100000})
        )
        svc.mark_overdue("p1", 150)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "p1", "principal": 100000})
        )
        assert len(prov_events) >= 1
        payload = prov_events[-1].payload
        assert payload["borrower"] == "p1"
        assert payload["bucket"] == "substandard"
        assert payload["provisioning_rate"] == 0.15
        assert payload["provisioning_amount"] == 15000.0  # 15% of 100000

    def test_npa_account_suspends_income_recognition(self) -> None:
        bus = LocalBus()
        income_events: list[Event] = []
        bus.subscribe(EventType.INCOME_RECOGNITION_SUSPENDED, lambda e: income_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "p2", "principal": 50000})
        )
        svc.mark_overdue("p2", 150)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "p2", "principal": 50000})
        )
        assert len(income_events) == 1
        payload = income_events[0].payload
        assert payload["borrower"] == "p2"
        assert payload["bucket"] == "substandard"

    def test_income_suspension_only_once(self) -> None:
        bus = LocalBus()
        income_events: list[Event] = []
        bus.subscribe(EventType.INCOME_RECOGNITION_SUSPENDED, lambda e: income_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "p3", "principal": 50000})
        )
        svc.mark_overdue("p3", 150)
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "p3", "principal": 50000})
        )
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "p3", "principal": 50000})
        )
        assert len(income_events) == 1

    def test_standard_account_does_not_suspend_income(self) -> None:
        bus = LocalBus()
        income_events: list[Event] = []
        bus.subscribe(EventType.INCOME_RECOGNITION_SUSPENDED, lambda e: income_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "p4", "principal": 50000})
        )
        svc.handle(
            Event(event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "p4", "principal": 50000})
        )
        assert len(income_events) == 0  # standard bucket, no suspension

    def test_sma_event_emitted(self) -> None:
        bus = LocalBus()
        sma_events: list[Event] = []
        bus.subscribe(EventType.SMA_CLASSIFIED, lambda e: sma_events.append(e))
        svc = npa(bus=bus)
        bus.start()
        svc.handle(
            Event(
                event_type=EventType.LOAN_ORIGINATED, source="test", payload={"borrower": "sma1", "principal": 100000}
            )
        )
        svc.mark_overdue("sma1", 45)
        svc.handle(
            Event(
                event_type=EventType.DEFAULT_OCCURRED, source="test", payload={"borrower": "sma1", "principal": 100000}
            )
        )
        assert len(sma_events) == 1
        assert sma_events[0].payload["sma_bucket"] == "sma_1"
