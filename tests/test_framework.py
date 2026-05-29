"""Exhaustive tests for the underwrite framework.

Covers: Configuration, Identity, Event, EventBus, Store, NanoService, Runtime.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from underwrite.__bus__ import LocalBus
from underwrite.__config__ import SERVICE_NAMES, Configuration
from underwrite.__events__ import Event
from underwrite.__exceptions__ import (
    ServiceNotFoundError,)
from underwrite.__identity__ import Identity
from underwrite.__runtime__ import Runtime
from underwrite.__store__ import FileStore, MemoryStore
from underwrite.services.base import NanoService

# =============================================================================
# Configuration
# =============================================================================


class TestConfiguration:

    def test_default_creates_all_services_disabled(self) -> None:
        config: Configuration = Configuration.default()
        assert len(config.services) == len(SERVICE_NAMES)
        for svc in config.services.values():
            assert svc.enabled is False

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        path: str = str(tmp_path / "config.json")
        config: Configuration = Configuration.default()
        config.services["mechanism"].enabled = True
        config.services["risk"].enabled = True
        config.save(path)
        loaded: Configuration = Configuration.load(path)
        assert loaded.services["mechanism"].enabled is True
        assert loaded.services["risk"].enabled is True
        assert loaded.services["audit"].enabled is False

    def test_enabled_services_returns_names(self) -> None:
        config: Configuration = Configuration.default()
        config.services["mechanism"].enabled = True
        config.services["audit"].enabled = True
        enabled: list[str] = config.enabled_services()
        assert "mechanism" in enabled
        assert "audit" in enabled
        assert "risk" not in enabled

    def test_env_overrides(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("UNDERWRITE_BUS_BACKEND", "sqs")
        monkeypatch.setenv("UNDERWRITE_LOG_LEVEL", "DEBUG")
        config: Configuration = Configuration.load()
        assert config.bus.backend == "sqs"
        assert config.logging.level == "DEBUG"

    def test_to_dict_serialises(self) -> None:
        config: Configuration = Configuration.default()
        d: dict[str, Any] = config.to_dict()
        assert "bus" in d
        assert "store" in d
        assert "services" in d
        assert len(d["services"]) == len(SERVICE_NAMES)


# =============================================================================
# Identity
# =============================================================================


class TestIdentity:

    def test_create_generates_keypair(self) -> None:
        identity: Identity = Identity.create("test-svc")
        assert identity.service_id == "test-svc"
        assert len(identity.public_key) > 0

    def test_sign_and_verify(self) -> None:
        identity: Identity = Identity.create("svc")
        payload: str = "message:123"
        sig: str = identity.sign(payload)
        assert identity.verify(payload, sig)

    def test_verify_rejects_tampered(self) -> None:
        identity: Identity = Identity.create("svc")
        payload: str = "message:123"
        sig: str = identity.sign(payload)
        assert identity.verify(payload + "x", sig) is False

    def test_attest_adds_provenance(self) -> None:
        identity: Identity = Identity.create("attestor")
        tx: dict[str, Any] = {"action": "add_seed", "user": "bank"}
        attested: dict[str, Any] = identity.attest(tx)
        assert attested["attested_by"] == "attestor"
        assert attested["attested_sig"] != ""

    def test_unique_keys_per_service(self) -> None:
        id1: Identity = Identity.create("svc1")
        id2: Identity = Identity.create("svc2")
        assert id1.public_key != id2.public_key


# =============================================================================
# Event
# =============================================================================


class TestEvent:

    def test_default_fields(self) -> None:
        event: Event = Event(event_type="test.event", source="testsvc")
        assert event.event_id != ""
        assert event.timestamp != ""
        assert event.correlation_id != ""

    def test_frozen_dataclass(self) -> None:
        event: Event = Event(event_type="a", source="s")
        with pytest.raises(AttributeError):
            event.event_type = "changed"  # type: ignore[misc]

    def test_payload_round_trip(self) -> None:
        event: Event = Event(event_type="x", source="s", payload={"a": 1})
        assert event.payload["a"] == 1


# =============================================================================
# EventBus (LocalBus)
# =============================================================================


class TestLocalBus:

    def test_publish_and_deliver(self) -> None:
        bus: LocalBus = LocalBus()
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.start()
        bus.publish(Event(event_type="test.event", source="test"))
        time.sleep(0.01)
        assert len(received) == 1
        assert received[0].event_type == "test.event"

    def test_wildcard_subscriber(self) -> None:
        bus: LocalBus = LocalBus()
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("*", handler)
        bus.start()
        bus.publish(Event(event_type="ev1", source="s"))
        bus.publish(Event(event_type="ev2", source="s"))
        time.sleep(0.01)
        assert len(received) == 2

    def test_unsubscribe(self) -> None:
        bus: LocalBus = LocalBus()
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        sid: str = bus.subscribe("test.event", handler)
        bus.unsubscribe(sid)
        bus.start()
        bus.publish(Event(event_type="test.event", source="test"))
        time.sleep(0.01)
        assert len(received) == 0

    def test_handler_exception_does_not_crash(self) -> None:
        bus: LocalBus = LocalBus()

        def failing(event: Event) -> None:
            raise ValueError("oops")

        ok: list[str] = []

        def ok_handler(event: Event) -> None:
            ok.append(event.event_type)

        bus.subscribe("test", failing)
        bus.subscribe("test", ok_handler)
        bus.start()
        bus.publish(Event(event_type="test", source="test"))
        time.sleep(0.01)
        assert ok == ["test"]

    def test_stop_clears_handlers(self) -> None:
        bus: LocalBus = LocalBus()
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("test", handler)
        bus.start()
        bus.stop()
        bus.publish(Event(event_type="test", source="test"))
        time.sleep(0.01)
        assert len(received) == 0


# =============================================================================
# Store
# =============================================================================


class TestMemoryStore:

    def test_set_and_get(self) -> None:
        store: MemoryStore = MemoryStore()
        store.set("key1", [1, 2, 3])
        assert store.get("key1") == [1, 2, 3]

    def test_get_missing(self) -> None:
        store: MemoryStore = MemoryStore()
        assert store.get("nonexistent") is None

    def test_delete(self) -> None:
        store: MemoryStore = MemoryStore()
        store.set("key", "val")
        assert store.delete("key") is True
        assert store.delete("key") is False

    def test_exists(self) -> None:
        store: MemoryStore = MemoryStore()
        assert store.exists("k") is False
        store.set("k", "v")
        assert store.exists("k") is True

    def test_keys_with_pattern(self) -> None:
        store: MemoryStore = MemoryStore()
        store.set("a:1", 1)
        store.set("a:2", 2)
        store.set("b:1", 3)
        assert len(store.keys("a:")) == 2
        assert "b:1" in store.keys()

    def test_thread_safety(self) -> None:
        store: MemoryStore = MemoryStore()
        errors: list[Exception] = []
        lock: threading.Lock = threading.Lock()

        def writer(i: int) -> None:
            try:
                for _ in range(100):
                    store.set(f"key:{i}", i)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads: list[threading.Thread] = [
            threading.Thread(target=writer, args=(i,)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0


class TestFileStore:

    def test_persistence(self, tmp_path: Path) -> None:
        store: FileStore = FileStore(str(tmp_path))
        store.set("user:alice", {"credit": 100.0})
        store.set("user:bob", {"credit": 50.0})
        store2: FileStore = FileStore(str(tmp_path))
        assert store2.get("user:alice") == {"credit": 100.0}
        assert store2.get("user:bob") == {"credit": 50.0}

    def test_delete(self, tmp_path: Path) -> None:
        store: FileStore = FileStore(str(tmp_path))
        store.set("key", "val")
        assert store.delete("key") is True
        assert store.delete("key") is False

    def test_keys(self, tmp_path: Path) -> None:
        store: FileStore = FileStore(str(tmp_path))
        store.set("a:x", 1)
        store.set("a:y", 2)
        all_keys: list[str] = store.keys()
        filtered: list[str] = store.keys("a:")
        assert len(filtered) >= 2
        assert "b:z" not in all_keys


# =============================================================================
# NanoService base
# =============================================================================


class ServiceHelper(NanoService):

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.handled: list[Event] = []

    def handle(self, event: Event) -> None:
        self.handled.append(event)
        self.emit("response", {"received": event.event_type},
                  correlation_id=event.correlation_id)


class TestNanoService:

    def test_service_id(self) -> None:
        svc: ServiceHelper = ServiceHelper(service_id="mysvc")
        assert svc.service_id == "mysvc"

    def test_identity_auto_created(self) -> None:
        svc: ServiceHelper = ServiceHelper(service_id="test")
        assert svc.service_id == "test"
        sig: str = svc.sign_event("test_payload")
        assert len(sig) > 0

    def test_emit_publishes_event(self) -> None:
        bus: LocalBus = LocalBus()
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("custom.event", handler)
        svc: ServiceHelper = ServiceHelper(service_id="emitter", bus=bus)
        svc.emit("custom.event", {"msg": "hello"})
        bus.start()
        time.sleep(0.01)
        assert len(received) == 1
        assert received[0].event_type == "custom.event"

    def test_event_has_signature(self) -> None:
        svc: ServiceHelper = ServiceHelper(service_id="signer")
        event: Event = svc.emit("signed.event", {"data": 1})
        assert event.signature != ""

    def test_subscribe_receives_events(self) -> None:
        bus: LocalBus = LocalBus()
        svc: ServiceHelper = ServiceHelper(service_id="subscriber", bus=bus)
        svc.subscribe("incoming")
        bus.start()
        svc.start()
        bus.publish(Event(event_type="incoming", source="test"))
        time.sleep(0.01)
        assert len(svc.handled) == 1
        assert svc.handled[0].event_type == "incoming"

    def test_stop_unsubscribes(self) -> None:
        bus: LocalBus = LocalBus()
        svc: ServiceHelper = ServiceHelper(service_id="stoppable", bus=bus)
        svc.subscribe("incoming")
        svc.start()
        svc.stop()
        bus.start()
        bus.publish(Event(event_type="incoming", source="test"))
        time.sleep(0.01)
        assert len(svc.handled) == 0

    def test_dispatched_event_triggers_response(self) -> None:
        bus: LocalBus = LocalBus()
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("response", handler)
        svc: ServiceHelper = ServiceHelper(service_id="responder", bus=bus)
        svc.subscribe("request")
        bus.start()
        svc.start()
        bus.publish(
            Event(event_type="request", source="test", correlation_id="corr-1"))
        time.sleep(0.01)
        assert len(received) >= 1
        assert received[0].payload["received"] == "request"


# =============================================================================
# Runtime
# =============================================================================


class TestRuntime:

    def test_start_stop(self) -> None:
        rt: Runtime = Runtime()
        rt.register("mechanism")
        rt.wire("mechanism")
        rt.start(["mechanism"])
        svc = rt.get("mechanism")
        assert svc is not None
        assert svc.is_running is True
        rt.stop()
        assert svc.is_running is False

    def test_unknown_service_raises(self) -> None:
        rt: Runtime = Runtime()
        with pytest.raises(ServiceNotFoundError):
            rt.register("nonexistent")

    def test_publish_event(self) -> None:
        received: list[Event] = []

        def handler(event: Event) -> None:
            received.append(event)

        rt: Runtime = Runtime()
        rt.bus.subscribe("custom", handler)
        rt.bus.start()
        rt.publish("custom", {"key": "val"})
        time.sleep(0.01)
        assert len(received) == 1
        assert received[0].event_type == "custom"

    def test_config_driven_start(self, tmp_path: Path) -> None:
        path: str = str(tmp_path / "config.json")
        config: Configuration = Configuration.default()
        config.services["mechanism"].enabled = True
        config.services["audit"].enabled = True
        config.save(path)
        config = Configuration.load(path)
        svc_names: list[str] = config.enabled_services()
        assert "mechanism" in svc_names
        assert "audit" in svc_names

    def test_dlq_health_check_registered(self) -> None:
        rt: Runtime = Runtime()
        status = rt.health.status()
        assert "dlq" in status["checks"]
        assert status["checks"]["dlq"]["ok"] is True
        assert "dead_letter_count" in status["checks"]["dlq"]

    def test_dlq_health_reflects_dead_letters(self) -> None:
        rt: Runtime = Runtime()
        bus = rt.bus
        bus.subscribe("fail.me", lambda e:
                      (_ for _ in ()).throw(RuntimeError("bang")))
        bus.start()
        bus.publish(Event(event_type="fail.me", source="t"))
        status = rt.health.status()
        assert status["checks"]["dlq"]["dead_letter_count"] >= 1
