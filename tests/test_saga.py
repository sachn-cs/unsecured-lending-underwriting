# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for Saga orchestration — execution, rollback, and persistence."""

from __future__ import annotations

import tempfile

import pytest
from helpers import FakeEmitter

from underwrite.exceptions import ProtocolError
from underwrite.saga import Orchestrator, Saga, SagaStep
from underwrite.store import Disk, InMemory


class TestSagaOrchestrator:
    def test_start_saga_returns_id(self) -> None:
        so = Orchestrator()
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
            ],
        )
        assert sid is not None
        assert isinstance(sid, str)

    def test_start_saga_rejects_empty_steps(self) -> None:
        so = Orchestrator()
        with pytest.raises(ProtocolError, match="must have at least one step"):
            so.start_saga("test", [])

    def test_execute_step_without_emitter_returns_false(self) -> None:
        so = Orchestrator()
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
            ],
        )
        ok = so.execute_step(sid, 0)
        assert ok is False

    def test_execute_all_completes_saga(self) -> None:
        so = Orchestrator()
        emitter = FakeEmitter()
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
            ],
        )
        ok = so.execute_all(sid)
        assert ok is True
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "completed"
        assert len(emitter.emitted) == 1

    def test_rollback_on_step_failure(self) -> None:
        so = Orchestrator()
        emitter = FakeEmitter(fail_on={"event.b"})
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
                SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
            ],
        )
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        assert saga.error != ""
        assert len(emitter.emitted) == 2  # forward event.a + compensation comp.a

    def test_rollback_skips_step_without_compensation(self) -> None:
        so = Orchestrator()
        emitter = FakeEmitter(fail_on={"event.b"})
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "a"}, compensate_event_type=None),
                SagaStep("s2", "event.b", {"k": "b"}, compensate_event_type=None),
            ],
        )
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        assert [ev[0] for ev in emitter.emitted] == ["event.a"]

    def test_get_saga_returns_none_for_unknown(self) -> None:
        so = Orchestrator()
        assert so.get_saga("nonexistent") is None

    def test_register_emitter_is_thread_safe(self) -> None:
        so = Orchestrator()
        results: list[str] = []

        def register_emitter(name: str) -> None:
            so.register_emitter(name, FakeEmitter())
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
        so = Orchestrator()
        emitter = FakeEmitter(fail_on={"event.b"}, fail_compensation=True)
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
                SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
            ],
        )
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        assert "compensation failed" in saga.error
        assert "step event.b failed" in saga.error

    def test_execute_step_stores_traceback(self) -> None:
        so = Orchestrator()
        emitter = FakeEmitter(fail_on={"event.fail"})
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.fail", {}, "comp.a", {}),
            ],
        )
        ok = so.execute_step(sid, 0)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert "step event.fail failed" in saga.error
        assert "Traceback" in saga.error
        assert "execute_step" in saga.error

    def test_lock_held_during_all_compensation_steps(self) -> None:
        so = Orchestrator()
        emitter = FakeEmitter(fail_on={"event.b"})
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
                SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
            ],
        )
        ok = so.execute_all(sid)
        assert ok is False
        saga = so.get_saga(sid)
        assert saga is not None
        assert saga.status == "rolled_back"
        # Verify error was accumulated properly under lock
        assert "step event.b failed" in saga.error


class TestSagaPersistence:
    def test_saga_persisted_to_store_on_start(self) -> None:
        store = InMemory()
        so = Orchestrator(store=store)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
            ],
        )
        raw = store.get(f"saga:{sid}")
        assert raw is not None
        assert raw["saga_id"] == sid
        assert raw["name"] == "test"

    def test_saga_loads_from_store_on_init(self) -> None:
        store = InMemory()
        inner = Orchestrator(store=store)
        sid = inner.start_saga(
            "restore-test",
            [
                SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
            ],
        )
        inner2 = Orchestrator(store=store)
        loaded = inner2.get_saga(sid)
        assert loaded is not None
        assert loaded.name == "restore-test"
        assert loaded.status == "started"

    def test_saga_persists_completed_steps(self) -> None:
        store = InMemory()
        so = Orchestrator(store=store)
        emitter = FakeEmitter()
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "v"}, "comp.a", {"k": "v"}),
            ],
        )
        so.execute_all(sid)
        raw = store.get(f"saga:{sid}")
        assert raw is not None
        assert raw["status"] == "completed"
        assert raw["completed_steps"] == [0]

    def test_saga_persists_rolled_back_status(self) -> None:
        store = InMemory()
        so = Orchestrator(store=store)
        emitter = FakeEmitter(fail_on={"event.b"})
        so.register_emitter("test", emitter)
        sid = so.start_saga(
            "test",
            [
                SagaStep("s1", "event.a", {"k": "a"}, "comp.a", {"k": "a"}),
                SagaStep("s2", "event.b", {"k": "b"}, "comp.b", {"k": "b"}),
            ],
        )
        so.execute_all(sid)
        raw = store.get(f"saga:{sid}")
        assert raw is not None
        assert raw["status"] == "rolled_back"
        assert "step event.b failed" in raw["error"]


class TestSagaCorruptLoad:
    def test_corrupt_record_does_not_drop_others(self) -> None:
        """A single corrupted saga record must not drop every other
        in-flight saga on startup."""
        from underwrite.store import InMemory

        store = InMemory()
        # Persist a valid saga
        orch1 = Orchestrator(store=store)
        orch1.register_emitter("a", FakeEmitter())
        sid1 = orch1.start_saga(
            "valid",
            [
                SagaStep(
                    name="s1",
                    forward_event_type="a",
                    forward_payload={},
                    compensate_event_type=None,
                    compensate_payload={},
                )
            ],
        )
        # Inject a corrupt record at a different key
        store.set("saga:corrupt", {"this": "is", "not": "a valid saga"})
        # New orchestrator should skip the corrupt record but load the valid one
        orch2 = Orchestrator(store=store)
        assert orch2.get_saga(sid1) is not None


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
        store = InMemory()
        store.set(
            "saga:bad",
            {
                "saga_id": "bad",
                "name": "test",
                "steps": [
                    {
                        "name": "a",
                        "forward_event_type": "ev.a",
                        "forward_payload": {},
                        "compensate_event_type": "comp.a",
                        "compensate_payload": {},
                    }
                ],
                "completed_steps": [99],
                "status": "started",
                "error": "",
                "started_at": "2024-01-01T00:00:00",
            },
        )
        so = Orchestrator(store=store)
        assert so.get_saga("bad") is None


class TestSagaFileStorePersistence:
    def test_saga_survives_orchestrator_restart_with_filestore(self) -> None:
        emitter = FakeEmitter()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Disk(data_dir=tmpdir)
            so1 = Orchestrator(store=store)
            so1.register_emitter("loan", emitter)
            sid = so1.start_saga(
                "loan",
                [
                    SagaStep("s1", "ev.a", {"k": "v"}, "comp.a", {"k": "c"}),
                ],
            )
            so1.execute_all(sid)
            saga1 = so1.get_saga(sid)
            assert saga1 is not None
            assert saga1.status == "completed"

            so2 = Orchestrator(store=store)
            saga2 = so2.get_saga(sid)
            assert saga2 is not None
            assert saga2.status == "completed"
            assert len(saga2.steps) == 1
            assert saga2.completed_steps == [0]

    def test_incomplete_saga_loaded_and_replayable_with_filestore(self) -> None:
        emitter = FakeEmitter()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Disk(data_dir=tmpdir)
            so1 = Orchestrator(store=store)
            sid = so1.start_saga(
                "multi",
                [
                    SagaStep("s1", "ev.a", {}, "comp.a", {}),
                    SagaStep("s2", "ev.b", {}, "comp.b", {}),
                ],
            )
            so1.register_emitter("multi", emitter)
            so1.execute_step(sid, 0)
            assert len(emitter.emitted) == 1

            so2 = Orchestrator(store=store)
            so2.register_emitter("multi", emitter)
            result = so2.replay_saga(sid)
            assert result is True
            assert so2.get_saga(sid) is not None
            saga = so2.get_saga(sid)
            assert saga is not None
            assert saga.status == "completed"
            assert len(emitter.emitted) == 2
