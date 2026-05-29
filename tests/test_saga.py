"""Tests for Saga orchestration — execution and rollback."""

from __future__ import annotations

import pytest

from underwrite.__exceptions__ import ProtocolError
from underwrite.__saga__ import Saga, SagaOrchestrator, SagaStep
from underwrite.__store__ import MemoryStore


class TestSagaOrchestrator:

    def test_start_saga_returns_id(self) -> None:
        so = SagaOrchestrator()
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
        ])
        assert sid is not None
        assert isinstance(sid, str)

    def test_start_saga_rejects_empty_steps(self) -> None:
        so = SagaOrchestrator()
        with pytest.raises(ProtocolError, match="must have at least one step"):
            so.start_saga("test", [])

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

            def emit(self,
                     et: str,
                     payload: dict,
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


class TestSagaPersistence:

    def test_saga_persisted_to_store_on_start(self) -> None:
        store = MemoryStore()
        so = SagaOrchestrator(store=store)
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
        ])
        raw = store.get(f"saga:{sid}")
        assert raw is not None
        assert raw["saga_id"] == sid
        assert raw["name"] == "test"

    def test_saga_loads_from_store_on_init(self) -> None:
        store = MemoryStore()
        inner = SagaOrchestrator(store=store)
        sid = inner.start_saga("restore-test", [
            SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
        ])
        inner2 = SagaOrchestrator(store=store)
        loaded = inner2.get_saga(sid)
        assert loaded is not None
        assert loaded.name == "restore-test"
        assert loaded.status == "started"

    def test_saga_persists_completed_steps(self) -> None:
        store = MemoryStore()
        so = SagaOrchestrator(store=store)
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
        so.execute_all(sid)
        raw = store.get(f"saga:{sid}")
        assert raw is not None
        assert raw["status"] == "completed"
        assert raw["completed_steps"] == [0]

    def test_saga_persists_rolled_back_status(self) -> None:
        store = MemoryStore()
        so = SagaOrchestrator(store=store)

        class FailingEmitter:

            def emit(self,
                     et: str,
                     payload: dict,
                     correlation_id: str = "") -> None:
                if et == "event.b":
                    raise RuntimeError("step b failed")

        so.register_emitter("test", FailingEmitter())
        sid = so.start_saga("test", [
            SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
            SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
        ])
        so.execute_all(sid)
        raw = store.get(f"saga:{sid}")
        assert raw is not None
        assert raw["status"] == "rolled_back"
        assert "step b failed" in raw["error"]


class TestSagaValidation:

    def test_validate_passes_for_valid_saga(self) -> None:
        saga = Saga(
            saga_id="s1",
            name="test",
            steps=[SagaStep("a", "ev.a", {}, "comp.a", {})],
            completed_steps=[0],
        )
        saga.validate()

    def test_validate_raises_on_out_of_range_step(self) -> None:
        saga = Saga(
            saga_id="s1",
            name="test",
            steps=[SagaStep("a", "ev.a", {}, "comp.a", {})],
            completed_steps=[5],
        )
        with pytest.raises(ProtocolError, match="out of range"):
            saga.validate()

    def test_validate_raises_on_duplicate_step(self) -> None:
        saga = Saga(
            saga_id="s1",
            name="test",
            steps=[
                SagaStep("a", "ev.a", {}, "comp.a", {}),
                SagaStep("b", "ev.b", {}, "comp.b", {}),
            ],
            completed_steps=[0, 0],
        )
        with pytest.raises(ProtocolError, match="duplicate"):
            saga.validate()

    def test_validate_raises_on_non_increasing_steps(self) -> None:
        saga = Saga(
            saga_id="s1",
            name="test",
            steps=[
                SagaStep("a", "ev.a", {}, "comp.a", {}),
                SagaStep("b", "ev.b", {}, "comp.b", {}),
                SagaStep("c", "ev.c", {}, "comp.c", {}),
            ],
            completed_steps=[1, 0],
        )
        with pytest.raises(ProtocolError, match="strictly increasing"):
            saga.validate()

    def test_validate_raises_on_empty_steps(self) -> None:
        saga = Saga(
            saga_id="s1",
            name="test",
            steps=[],
        )
        with pytest.raises(ProtocolError, match="no steps"):
            saga.validate()

    def test_corrupted_saga_rejected_on_load(self) -> None:
        store = MemoryStore()
        store.set(
            "saga:bad", {
                "saga_id": "bad",
                "name": "test",
                "steps": [{
                    "name": "a",
                    "forward_event_type": "ev.a",
                    "forward_payload": {},
                    "compensate_event_type": "comp.a",
                    "compensate_payload": {}
                }],
                "completed_steps": [99],
                "status": "started",
                "error": "",
                "started_at": "2024-01-01T00:00:00",
            })
        so = SagaOrchestrator(store=store)
        assert so.get_saga("bad") is None
