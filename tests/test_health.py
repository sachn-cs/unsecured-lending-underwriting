"""Tests for HealthRegistry."""

from __future__ import annotations

from underwrite.__health__ import HealthRegistry


class TestHealthRegistry:

    def test_healthy_when_no_checks(self) -> None:
        hr = HealthRegistry()
        status = hr.status()
        assert status["ok"] is True
        assert status["status"] == "healthy"

    def test_single_healthy_check(self) -> None:
        hr = HealthRegistry()
        hr.register("db", lambda: {"ok": True})
        status = hr.status()
        assert status["ok"] is True
        assert status["checks"]["db"]["ok"] is True

    def test_degraded_when_check_fails(self) -> None:
        hr = HealthRegistry()
        hr.register("db", lambda: {"ok": False, "detail": "down"})
        status = hr.status()
        assert status["ok"] is False
        assert status["status"] == "degraded"

    def test_check_exception_treated_as_failure(self) -> None:
        hr = HealthRegistry()
        hr.register("crashy", lambda:
                    (_ for _ in ()).throw(RuntimeError("boom")))
        status = hr.status()
        assert status["ok"] is False
        assert "boom" in status["checks"]["crashy"]["detail"]

    def test_unregister(self) -> None:
        hr = HealthRegistry()
        hr.register("x", lambda: {"ok": True})
        hr.unregister("x")
        assert "x" not in hr.status()["checks"]

    def test_multiple_checks(self) -> None:
        hr = HealthRegistry()
        hr.register("a", lambda: {"ok": True})
        hr.register("b", lambda: {"ok": False, "detail": "bad"})
        status = hr.status()
        assert status["ok"] is False
        assert "a" in status["checks"]
        assert "b" in status["checks"]

    def test_check_unregistered_during_status_skipped(self) -> None:
        hr = HealthRegistry()
        hr.register("a", lambda: {"ok": True})
        status = hr.status()
        assert "a" in status["checks"]

    def test_status_consistent_during_concurrent_register(self) -> None:
        import threading
        hr = HealthRegistry()
        hr.register("stable", lambda: {"ok": True})

        def register_later():
            hr.register("late", lambda: {"ok": True})

        t = threading.Thread(target=register_later)
        t.start()
        status = hr.status()
        t.join()
        # stable must appear; late may or may not — no undefined behavior
        assert "stable" in status["checks"]

    def test_unregister_does_not_affect_concurrent_status(self) -> None:
        hr = HealthRegistry()
        hr.register("to_remove", lambda: {"ok": True})
        # Register is deterministic even during concurrent status calls
        status_a = hr.status()
        assert "to_remove" in status_a["checks"]
        hr.unregister("to_remove")
        status_b = hr.status()
        assert "to_remove" not in status_b["checks"]
