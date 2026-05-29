"""End-to-end tests — full event flow through Runtime.

Tests verify the complete pipeline: Runtime.publish() → bus → dispatch
→ service handle → emit → downstream service receives.
"""

from __future__ import annotations

from underwrite.__config__ import Configuration
from underwrite.__events__ import Event, EventType
from underwrite.__runtime__ import Runtime


def _memory_runtime(enable_metrics: bool = True) -> Runtime:
    """Returns a Runtime backed by MemoryStore for test isolation."""
    cfg = Configuration.default()
    cfg.store.backend = "memory"
    cfg.metrics.enabled = enable_metrics
    cfg.tracing.enabled = False
    cfg.metrics.export_interval = 0  # disable export thread
    return Runtime(config=cfg)


class TestPublishFlow:

    def test_publish_through_runtime_delivers_to_service(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        rt.register("audit")
        rt.wire("audit")
        bus.start()
        rt.start(["audit"])
        bus.publish(
            Event(event_type=EventType.LOAN_ORIGINATED,
                  source="test",
                  payload={
                      "aadhaar": "1234-5678-9012",
                      "principal": 50000
                  }))
        audit = rt.get("audit")
        records = [
            e for e in audit.ledger
            if e["event_type"] == EventType.LOAN_ORIGINATED
        ]
        assert len(records) == 1
        assert records[0]["payload"]["aadhaar"] == "***REDACTED***"
        rt.stop()

    def test_runtime_publish_method_creates_event(self) -> None:
        rt = Runtime()
        bus = rt.bus
        received: list[Event] = []
        bus.subscribe("*", lambda e: received.append(e))
        bus.start()
        bus.publish(
            Event(event_type="custom.test",
                  source="test",
                  payload={"key": "value"}))
        assert any(e.event_type == "custom.test" for e in received)
        rt.stop()

    def test_multiple_services_receive_same_event(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        rt.register("mechanism")
        rt.register("audit")
        rt.wire("mechanism")
        rt.wire("audit")
        bus.start()
        rt.start(["mechanism", "audit"])
        mechanism = rt.get("mechanism")
        mechanism.handle(
            Event(event_type="mechanism",
                  source="test",
                  payload={
                      "command": "add_seed",
                      "user": "bank",
                      "base_budget": 200000
                  }))
        audit = rt.get("audit")
        seed_events = [
            e for e in audit.ledger if e["event_type"] == EventType.SEED_ADDED
        ]
        assert len(seed_events) >= 1
        state = rt.store.get("protocol:state")
        assert state is not None
        assert "bank" in state["seeds"]
        rt.stop()

    def test_service_emits_through_bus_downstream(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        all_events: list[Event] = []
        bus.subscribe("*", lambda e: all_events.append(e))
        rt.register("mechanism")
        rt.wire("mechanism")
        bus.start()
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        svc.handle(
            Event(event_type="mechanism",
                  source="test",
                  payload={
                      "command": "add_seed",
                      "user": "bank",
                      "base_budget": 300000
                  }))
        emitted_types = {e.event_type for e in all_events}
        assert EventType.SEED_ADDED in emitted_types
        rt.stop()

    def test_audit_records_emitted_events_via_wiring(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        rt.register("mechanism")
        rt.register("audit")
        rt.wire("mechanism")
        rt.wire("audit")
        bus.start()
        rt.start(["mechanism", "audit"])
        svc = rt.get("mechanism")
        svc.handle(
            Event(event_type="mechanism",
                  source="test",
                  payload={
                      "command": "add_seed",
                      "user": "bank",
                      "base_budget": 400000
                  }))
        audit = rt.get("audit")
        seed_records = audit.events_by_type(EventType.SEED_ADDED)
        assert len(seed_records) >= 1
        rt.stop()


class TestRuntimeHealthE2E:

    def test_health_reflects_running_services(self) -> None:
        rt = Runtime()
        checks = rt.health.status()["checks"]
        assert "bus" in checks
        assert "store" in checks
        assert "services" in checks
        rt.register("mechanism")
        rt.wire("mechanism")
        rt.start(["mechanism"])
        checks = rt.health.status()["checks"]
        svc_check = checks.get("service:mechanism", {})
        assert svc_check.get("ok") is True

    def test_stopped_service_shows_unhealthy(self) -> None:
        rt = Runtime()
        rt.register("mechanism")
        rt.wire("mechanism")
        rt.start(["mechanism"])
        rt.stop()
        checks = rt.health.status()["checks"]
        svc_check = checks.get("service:mechanism", {})
        assert svc_check.get("ok") is False

    def test_bus_health_always_ok(self) -> None:
        rt = Runtime()
        checks = rt.health.status()["checks"]
        assert checks["bus"]["ok"] is True

    def test_store_health_always_ok(self) -> None:
        rt = Runtime()
        checks = rt.health.status()["checks"]
        assert checks["store"]["ok"] is True


class TestMetricsE2E:

    def test_metrics_recorded_when_enabled(self) -> None:
        rt = Runtime()
        assert rt.metrics is not None
        rt.metrics.increment("test.counter", {"label": "e2e"})
        snap = rt.metrics.snapshot()
        counters = snap.get("counters", {})
        assert any("test.counter" in k for k in counters)
        rt.stop()

    def test_events_emitted_increment_counter(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        rt.register("mechanism")
        rt.wire("mechanism")
        bus.start()
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        svc.handle(
            Event(event_type="mechanism",
                  source="test",
                  payload={
                      "command": "add_seed",
                      "user": "bank",
                      "base_budget": 50000
                  }))
        snap = rt.metrics.snapshot()
        counters = snap.get("counters", {})
        emitted_key = next(
            (k for k in counters if "events.emitted" in k and "mechanism" in k),
            None)
        assert emitted_key is not None
        rt.stop()

    def test_metrics_returns_collector_by_default(self) -> None:
        rt = Runtime()
        assert rt.metrics is not None


class TestGracefulShutdownE2E:

    def test_stop_with_active_service(self) -> None:
        rt = Runtime()
        bus = rt.bus
        rt.register("mechanism")
        rt.wire("mechanism")
        bus.start()
        rt.start(["mechanism"])
        assert rt.get("mechanism").is_running
        rt.stop()
        assert rt.get("mechanism").is_running is False

    def test_stop_idempotent(self) -> None:
        rt = Runtime()
        rt.register("mechanism")
        rt.wire("mechanism")
        rt.start(["mechanism"])
        rt.stop()
        rt.stop()
        rt.stop()
        assert rt.get("mechanism").is_running is False

    def test_stop_with_no_services(self) -> None:
        rt = Runtime()
        rt.stop()
        rt.stop()


class TestMultipleServiceCoordination:

    def test_mechanism_and_audit_coexist(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        rt.register("mechanism")
        rt.register("audit")
        rt.wire("mechanism")
        rt.wire("audit")
        bus.start()
        rt.start(["mechanism", "audit"])
        assert rt.get("mechanism").is_running
        assert rt.get("audit").is_running
        svc = rt.get("mechanism")
        svc.handle(
            Event(event_type="mechanism",
                  source="test",
                  payload={
                      "command": "add_seed",
                      "user": "bank",
                      "base_budget": 100000
                  }))
        audit = rt.get("audit")
        assert len(audit.ledger) >= 1
        rt.stop()
        assert rt.get("mechanism").is_running is False
        assert rt.get("audit").is_running is False

    def test_store_shared_between_services(self) -> None:
        rt = _memory_runtime()
        bus = rt.bus
        rt.register("mechanism")
        rt.register("audit")
        rt.wire("mechanism")
        rt.wire("audit")
        bus.start()
        rt.start(["mechanism", "audit"])
        mech_svc = rt.get("mechanism")
        mech_svc.handle(
            Event(event_type="mechanism",
                  source="test",
                  payload={
                      "command": "add_seed",
                      "user": "bank",
                      "base_budget": 100000
                  }))
        audit_svc = rt.get("audit")
        state_from_mech = mech_svc.store.get("protocol:state")
        state_from_audit = audit_svc.store.get("protocol:state")
        assert state_from_mech is not None
        assert state_from_audit is not None
        assert state_from_mech == state_from_audit
        rt.stop()
