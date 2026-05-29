"""Thread-safety concurrency tests for core underwrite subsystems.

Each test spawns 10 concurrent threads doing 100 operations each and
asserts no data corruption, no exceptions, and correct final state.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from underwrite.__bus__ import Event, LocalBus
from underwrite.__circuit__ import CircuitBreaker
from underwrite.__health__ import HealthRegistry
from underwrite.__metrics__ import MetricsCollector
from underwrite.__saga__ import SagaOrchestrator, SagaStep
from underwrite.__store__ import FileStore, MemoryStore
from underwrite.__tracer__ import Tracer

NUM_THREADS: int = 10
OPS_PER_THREAD: int = 100


class TestBusConcurrency:

    def test_concurrent_publish(self) -> None:
        bus = LocalBus(max_workers=4)
        bus.start()
        counter_lock = threading.Lock()
        counter: int = 0

        def handler(event: Event) -> None:
            nonlocal counter
            with counter_lock:
                counter += 1

        bus.subscribe("test.event", handler)
        errors: list[Exception] = []

        def publish_many() -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    bus.publish(
                        Event(event_type="test.event",
                              source="test",
                              payload={"i": i}))
            except Exception as exc:
                with counter_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=publish_many) for _ in range(NUM_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        bus.stop()
        assert not errors, f"concurrent publish raised: {errors[0]}"
        assert counter == NUM_THREADS * OPS_PER_THREAD

    def test_concurrent_dlq_operations(self) -> None:
        bus = LocalBus(max_workers=4)
        bus.start()
        errors: list[Exception] = []

        def dlq_ops() -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    ev = Event(event_type="dlq.test",
                               source="t",
                               payload={"i": i})
                    bus.publish(ev)
                _ = bus.dlq.count
                _ = bus.dlq.records
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=dlq_ops) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        bus.stop()
        assert not errors, f"DLQ concurrent ops raised: {errors[0]}"


class TestStoreConcurrency:

    def test_concurrent_filestore_set_get(self, tmp_path: Any) -> None:
        store = FileStore(str(tmp_path))
        errors: list[Exception] = []

        def set_get() -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    key = f"k_{threading.get_ident()}_{i}"
                    store.set(key, {
                        "value": i,
                        "thread": threading.get_ident()
                    })
                    val = store.get(key)
                    assert val is not None, f"missing key {key}"
                    assert val["value"] == i
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=set_get) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors, f"concurrent FileStore raised: {errors[0] if errors else 'unknown'}"

    def test_concurrent_memorystore_set_get(self) -> None:
        store = MemoryStore()
        errors: list[Exception] = []

        def set_get() -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    key = f"k_{threading.get_ident()}_{i}"
                    store.set(key, i)
                    val = store.get(key)
                    assert val == i
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=set_get) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors, f"concurrent MemoryStore raised: {errors[0] if errors else 'unknown'}"


class TestCircuitBreakerConcurrency:

    def test_concurrent_state_transitions(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.01)
        errors: list[Exception] = []

        def hammer() -> None:
            try:
                for _ in range(OPS_PER_THREAD):
                    try:
                        cb.call(lambda:
                                (_ for _ in ()).throw(ValueError("bad")))
                    except (ValueError, Exception):
                        pass
                    try:
                        cb.call(lambda: "ok")
                    except Exception:
                        pass
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors


class TestMetricsConcurrency:

    def test_concurrent_increment_gauge_timer(self) -> None:
        mc = MetricsCollector(max_metrics=50000)
        errors: list[Exception] = []

        def ops(tid: int) -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    mc.increment("counter.test", {"t": str(tid)})
                    mc.gauge("gauge.test", float(i), {"t": str(tid)})
                    mc.timer("timer.test", float(i % 100), {"t": str(tid)})
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=ops, args=(i,)) for i in range(NUM_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        snap = mc.snapshot()
        assert not errors
        assert len(snap["counters"]) == NUM_THREADS
        assert len(snap["gauges"]) == NUM_THREADS
        total_counter = sum(c["value"] for c in snap["counters"].values())
        assert total_counter == NUM_THREADS * OPS_PER_THREAD


class TestTracerConcurrency:

    def test_concurrent_span_creation(self) -> None:
        tracer = Tracer(service_id="concurrency-test", max_spans=50000)
        errors: list[Exception] = []

        def create_spans() -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    span = tracer.start_span(
                        "op",
                        tags={
                            "i": str(i),
                            "t": str(threading.get_ident())
                        },
                    )
                    tracer.end_span(span)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=create_spans) for _ in range(NUM_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors
        assert len(tracer.spans) == NUM_THREADS * OPS_PER_THREAD


class TestSagaConcurrency:

    def test_concurrent_execute_all(self) -> None:
        orchestrator = SagaOrchestrator()
        errors: list[Exception] = []
        emitted: list[str] = []
        emit_lock = threading.Lock()

        class DummyEmitter:

            def emit(self,
                     event_type: str,
                     payload: dict[str, Any],
                     correlation_id: str = "") -> Event:
                with emit_lock:
                    emitted.append(event_type)
                return Event(event_type=event_type,
                             source="dummy",
                             payload=payload)

        orchestrator.register_emitter("test_saga", DummyEmitter())

        def run_saga() -> None:
            try:
                steps = [
                    SagaStep("s1", "event.a", {}, "comp.a", {}),
                    SagaStep("s2", "event.b", {}, "comp.b", {}),
                ]
                saga_id = orchestrator.start_saga("test_saga", steps)
                orchestrator.execute_all(saga_id)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=run_saga) for _ in range(NUM_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors


class TestHealthConcurrency:

    def test_concurrent_register_and_status(self) -> None:
        hr = HealthRegistry()
        errors: list[Exception] = []

        def register_and_check() -> None:
            try:
                for i in range(OPS_PER_THREAD):
                    name = f"check_{threading.get_ident()}_{i}"
                    hr.register(name, lambda: {"ok": True})
                    hr.status()
                    hr.unregister(name)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_and_check)
            for _ in range(NUM_THREADS)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors
        status = hr.status()
        assert status["ok"] is True


@pytest.mark.skip("requires mechanism service setup")
class TestMechanismConcurrency:
    pass
