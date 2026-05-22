"""Tests for Saga orchestration — execution and rollback."""

from __future__ import annotations

from underwrite.__saga__ import SagaOrchestrator, SagaStep


class TestSagaOrchestrator:

    def test_start_saga_returns_id(self) -> None:
        so = SagaOrchestrator()
        sid = so.start_saga("test", [])
        assert sid is not None

    def test_execute_step_without_emitter_returns_false(self) -> None:
        so = SagaOrchestrator()
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
        ])
        ok = so.execute_step(sid, 0)
        assert ok is False

    def test_execute_all_completes_saga(self) -> None:
        so = SagaOrchestrator()
        emitted: list = []

        class FakeEmitter:

            def emit(self,
                     et: str,
                     payload: dict,
                     correlation_id: str = "") -> None:
                emitted.append((et, payload))

        so.register_emitter("test", FakeEmitter())
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
        ])
        ok = so.execute_all(sid)
        assert ok is True
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "completed"
        assert len(emitted) == 1

    def test_rollback_on_step_failure(self) -> None:
        so = SagaOrchestrator()
        emitted: list = []

        class FakeEmitter:

            def __init__(self):
                self._fail = False

            def emit(self,
                     et: str,
                     payload: dict,
                     correlation_id: str = "") -> None:
                if et == "event.b":
                    self._fail = True
                    raise RuntimeError("step b failed")
                emitted.append((et, payload))

        so.register_emitter("test", FakeEmitter())
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
            SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
        ])
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        assert saga.error != ""

    def test_get_saga_returns_none_for_unknown(self) -> None:
        so = SagaOrchestrator()
        assert so.get_saga("nonexistent") is None

    def test_register_emitter_is_thread_safe(self) -> None:
        so = SagaOrchestrator()
        results: list = []

        def register_emitter(name: str) -> None:
            so.register_emitter(name, "emitter")
            results.append(name)

        import threading
        t1 = threading.Thread(target=register_emitter, args=("saga-a",))
        t2 = threading.Thread(target=register_emitter, args=("saga-b",))
        t1.start()
        t2.start()
        t1.join(timeout=1.0)
        t2.join(timeout=1.0)
        assert len(results) == 2
        assert "saga-a" in results
        assert "saga-b" in results

    def test_compensation_failure_accumulates_errors_under_lock(self) -> None:
        so = SagaOrchestrator()
        emitted: list = []

        class FailingStepAndCompensateEmitter:

            def __init__(self):
                self._fail = False

            def emit(self,
                     et: str,
                     payload: dict,
                     correlation_id: str = "") -> None:
                if et == "event.b":
                    self._fail = True
                    raise RuntimeError("step b failed")
                if et.startswith("comp."):
                    raise RuntimeError(f"compensation failed for {et}")
                emitted.append((et, payload))

        so.register_emitter("test", FailingStepAndCompensateEmitter())
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
            SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
        ])
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        assert "compensation failed" in saga.error
        assert "step b failed" in saga.error

    def test_execute_step_stores_traceback(self) -> None:
        so = SagaOrchestrator()
        emitted: list = []

        class FailingEmitter:

            def emit(self, et: str, payload: dict,
                     correlation_id: str = "") -> None:
                if et == "event.fail":
                    raise RuntimeError("step failure detail")
                emitted.append((et, payload))

        so.register_emitter("test", FailingEmitter())
        sid = so.start_saga("test", [
            SagaStep("s1", "event.fail", {}, "comp.a", {}),
        ])
        ok = so.execute_step(sid, 0)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert "step failure detail" in saga.error
        assert "Traceback" in saga.error
        assert "execute_step" in saga.error

    def test_lock_held_during_all_compensation_steps(self) -> None:
        so = SagaOrchestrator()
        emitted: list = []

        class LockCheckEmitter:

            def emit(self,
                     et: str,
                     payload: dict,
                     correlation_id: str = "") -> None:
                if et == "event.b":
                    raise RuntimeError("step b failed")
                emitted.append((et, payload))

        so.register_emitter("test", LockCheckEmitter())
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
            SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
        ])
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        # Verify error was accumulated properly under lock
        assert "step b failed" in saga.error
