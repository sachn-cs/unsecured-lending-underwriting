"""Tests for ServiceSupervisor — failure tracking, backoff, and health."""

from __future__ import annotations

import pytest

from underwrite.__supervisor__ import ServiceSupervisor


class TestServiceSupervisor:
    """Tests for ServiceSupervisor — monitors service health and auto-restarts."""

    def test_initializes_with_no_failures(self) -> None:
        sup = ServiceSupervisor()
        health = sup.health()
        assert health["ok"] is True
        assert health["total_failures"] == 0
        assert health["restarting"] == []

    def test_record_failure_increments_count(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        result = sup.record_failure("svc-a")
        assert result is True
        health = sup.health()
        assert health["total_failures"] == 1
        assert "svc-a" in health["restarting"]

    def test_record_failure_returns_true_within_limit(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        for _ in range(3):
            result = sup.record_failure("svc-a")
            assert result is True

    def test_record_failure_returns_false_when_limit_exceeded(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        for _ in range(3):
            sup.record_failure("svc-a")
        result = sup.record_failure("svc-a")
        assert result is False

    def test_record_failure_multiple_services_independent(self) -> None:
        sup = ServiceSupervisor(max_restarts=2)
        sup.record_failure("svc-a")
        sup.record_failure("svc-b")
        sup.record_failure("svc-b")
        assert sup.record_failure("svc-a") is True  # only 1 failure
        assert sup.record_failure("svc-b") is False  # 3 failures > 2

    def test_record_success_resets_failure_count(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        sup.record_success("svc-a")
        health = sup.health()
        assert health["total_failures"] == 0
        assert "svc-a" not in health["restarting"]

    def test_record_success_noop_for_untracked_service(self) -> None:
        sup = ServiceSupervisor()
        sup.record_success("never-failed")
        assert sup.health()["total_failures"] == 0

    def test_reset_clears_failure_count(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        sup.reset("svc-a")
        health = sup.health()
        assert health["total_failures"] == 0
        assert "svc-a" not in health["restarting"]

    def test_reset_noop_for_untracked_service(self) -> None:
        sup = ServiceSupervisor()
        sup.reset("never-failed")
        assert sup.health()["total_failures"] == 0

    def test_backoff_returns_zero_for_no_failures(self) -> None:
        sup = ServiceSupervisor()
        assert sup.backoff("svc-a") == 0.0

    def test_backoff_exponential_increase(self) -> None:
        sup = ServiceSupervisor(backoff_seconds=1.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(1.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(2.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(4.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(8.0)

    def test_backoff_caps_at_sixty_seconds(self) -> None:
        sup = ServiceSupervisor(backoff_seconds=1.0)
        for _ in range(10):
            sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == 60.0

    def test_backoff_with_custom_base(self) -> None:
        sup = ServiceSupervisor(backoff_seconds=5.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(5.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(10.0)
        sup.record_failure("svc-a")
        assert sup.backoff("svc-a") == pytest.approx(20.0)

    def test_health_ok_when_no_failures_exceed_max(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        sup.record_failure("svc-a")
        sup.record_failure("svc-b")
        assert sup.health()["ok"] is True

    def test_health_not_ok_when_failure_exceeds_max(self) -> None:
        sup = ServiceSupervisor(max_restarts=2)
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        assert sup.health()["ok"] is False

    def test_health_reflects_total_failures(self) -> None:
        sup = ServiceSupervisor(max_restarts=5)
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        sup.record_failure("svc-b")
        health = sup.health()
        assert health["total_failures"] == 3

    def test_health_restarting_lists_tracked_services(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        sup.record_failure("svc-a")
        sup.record_failure("svc-b")
        restarting = sup.health()["restarting"]
        assert sorted(restarting) == ["svc-a", "svc-b"]

    def test_max_restarts_one(self) -> None:
        sup = ServiceSupervisor(max_restarts=1)
        assert sup.record_failure("svc-a") is True  # count=1
        assert sup.record_failure("svc-a") is False  # count=2 > 1

    def test_max_restarts_zero(self) -> None:
        sup = ServiceSupervisor(max_restarts=0)
        assert sup.record_failure("svc-a") is False  # count=1 > 0

    def test_record_success_allows_restart_again(self) -> None:
        sup = ServiceSupervisor(max_restarts=2)
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        assert sup.record_failure("svc-a") is False  # exceeded
        sup.record_success("svc-a")
        assert sup.record_failure("svc-a") is True  # fresh start

    def test_should_restart_returns_true_within_limit(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        sup.record_failure("svc-a")
        assert sup.should_restart("svc-a") is True

    def test_should_restart_returns_false_when_limit_exceeded(self) -> None:
        sup = ServiceSupervisor(max_restarts=2)
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        sup.record_failure("svc-a")
        assert sup.should_restart("svc-a") is False

    def test_failing_services_returns_only_failing(self) -> None:
        sup = ServiceSupervisor(max_restarts=3)
        sup.record_failure("svc-a")
        sup.record_failure("svc-b")
        sup.record_failure("svc-b")
        sup.record_success("svc-a")  # healthy now
        failing = sup.failing_services()
        assert "svc-b" in failing
        assert "svc-a" not in failing
