"""Exhaustive tests for the underwrite framework.

Covers: Configuration, Keypair, Message, EventBus, Store, Core, Runtime.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from underwrite.bus import EventBus
from underwrite.config import HANDLER_NAMES, Configuration
from underwrite.exceptions import (
    ServiceNotFoundError,
)
from underwrite.keypair import Keypair
from underwrite.local import LocalBus
from underwrite.message import Message
from underwrite.runtime import Runtime
from underwrite.services.base import Core
from underwrite.store import Disk, InMemory

# =============================================================================
# Configuration
# =============================================================================


class TestConfiguration:
    def test_default_creates_all_services_disabled(self) -> None:
        config: Configuration = Configuration.default()
        assert len(config.services) == len(HANDLER_NAMES)
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
        monkeypatch.setenv("UNDERWRITE_BUS_BACKEND", "modal")
        monkeypatch.setenv("UNDERWRITE_LOG_LEVEL", "DEBUG")
        config: Configuration = Configuration.load()
        assert config.bus.backend == "modal"
        assert config.logging.level == "DEBUG"

    def test_to_dict_serialises(self) -> None:
        config: Configuration = Configuration.default()
        d: dict[str, Any] = config.to_dict()
        assert "bus" in d
        assert "store" in d
        assert "services" in d
        assert len(d["services"]) == len(HANDLER_NAMES)


# =============================================================================
# Keypair
# =============================================================================


class TestIdentity:
    def test_create_generates_keypair(self) -> None:
        identity: Keypair = Keypair.create("test-svc")
        assert identity.name == "test-svc"
        assert len(identity.public_key) > 0

    def test_sign_and_verify(self) -> None:
        identity: Keypair = Keypair.create("svc")
        payload: str = "message:123"
        sig: str = identity.sign(payload)
        assert identity.verify(payload, sig)

    def test_verify_rejects_tampered(self) -> None:
        identity: Keypair = Keypair.create("svc")
        payload: str = "message:123"
        sig: str = identity.sign(payload)
        assert identity.verify(payload + "x", sig) is False

    def test_unique_keys_per_service(self) -> None:
        id1: Keypair = Keypair.create("svc1")
        id2: Keypair = Keypair.create("svc2")
        assert id1.public_key != id2.public_key


# =============================================================================
# Message
# =============================================================================


class TestEvent:
    def test_default_fields(self) -> None:
        event: Message = Message(event_type="test.event", source="testsvc")
        assert event.event_id != ""
        assert event.timestamp != ""
        assert event.correlation_id != ""

    def test_frozen_dataclass(self) -> None:
        event: Message = Message(event_type="a", source="s")
        with pytest.raises(AttributeError):
            event.__setattr__("event_type", "changed")

    def test_payload_round_trip(self) -> None:
        event: Message = Message(event_type="x", source="s", payload={"a": 1})
        assert event.payload["a"] == 1


# =============================================================================
# EventBus (EventBus)
# =============================================================================


class TestEventBus:
    def test_publish_and_deliver(self) -> None:
        bus: EventBus = LocalBus()
        received: list[Message] = []

        def handler(event: Message) -> None:
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.start()
        bus.publish(Message(event_type="test.event", source="test"))
        time.sleep(0.01)
        assert len(received) == 1
        assert received[0].event_type == "test.event"

    def test_wildcard_subscriber(self) -> None:
        bus: EventBus = LocalBus()
        received: list[Message] = []

        def handler(event: Message) -> None:
            received.append(event)

        bus.subscribe("*", handler)
        bus.start()
        bus.publish(Message(event_type="ev1", source="s"))
        bus.publish(Message(event_type="ev2", source="s"))
        time.sleep(0.01)
        assert len(received) == 2

    def test_unsubscribe(self) -> None:
        bus: EventBus = LocalBus()
        received: list[Message] = []

        def handler(event: Message) -> None:
            received.append(event)

        sid: str = bus.subscribe("test.event", handler)
        bus.unsubscribe(sid)
        bus.start()
        bus.publish(Message(event_type="test.event", source="test"))
        time.sleep(0.01)
        assert len(received) == 0

    def test_handler_exception_does_not_crash(self) -> None:
        bus: EventBus = LocalBus()

        def failing(event: Message) -> None:
            raise ValueError("oops")

        ok: list[str] = []

        def ok_handler(event: Message) -> None:
            ok.append(event.event_type)

        bus.subscribe("test", failing)
        bus.subscribe("test", ok_handler)
        bus.start()
        bus.publish(Message(event_type="test", source="test"))
        time.sleep(0.01)
        assert ok == ["test"]

    def test_stop_clears_handlers(self) -> None:
        bus: EventBus = LocalBus()
        received: list[Message] = []

        def handler(event: Message) -> None:
            received.append(event)

        bus.subscribe("test", handler)
        bus.start()
        bus.stop()
        bus.publish(Message(event_type="test", source="test"))
        time.sleep(0.01)
        assert len(received) == 0


# =============================================================================
# Store
# =============================================================================


class TestMemoryStore:
    def test_set_and_get(self) -> None:
        store: InMemory = InMemory()
        store.set("key1", [1, 2, 3])
        assert store.get("key1") == [1, 2, 3]

    def test_get_missing(self) -> None:
        store: InMemory = InMemory()
        assert store.get("nonexistent") is None

    def test_delete(self) -> None:
        store: InMemory = InMemory()
        store.set("key", "val")
        assert store.delete("key") is True
        assert store.delete("key") is False

    def test_exists(self) -> None:
        store: InMemory = InMemory()
        assert store.exists("k") is False
        store.set("k", "v")
        assert store.exists("k") is True

    def test_keys_with_pattern(self) -> None:
        store: InMemory = InMemory()
        store.set("a:1", 1)
        store.set("a:2", 2)
        store.set("b:1", 3)
        assert len(store.keys("a:")) == 2
        assert "b:1" in store.keys()

    def test_thread_safety(self) -> None:
        store: InMemory = InMemory()
        errors: list[Exception] = []
        lock: threading.Lock = threading.Lock()

        def writer(i: int) -> None:
            try:
                for _ in range(100):
                    store.set(f"key:{i}", i)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads: list[threading.Thread] = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0


class TestFileStore:
    def test_persistence(self, tmp_path: Path) -> None:
        store: Disk = Disk(str(tmp_path))
        store.set("user:alice", {"credit": 100.0})
        store.set("user:bob", {"credit": 50.0})
        store2: Disk = Disk(str(tmp_path))
        assert store2.get("user:alice") == {"credit": 100.0}
        assert store2.get("user:bob") == {"credit": 50.0}

    def test_delete(self, tmp_path: Path) -> None:
        store: Disk = Disk(str(tmp_path))
        store.set("key", "val")
        assert store.delete("key") is True
        assert store.delete("key") is False

    def test_keys(self, tmp_path: Path) -> None:
        store: Disk = Disk(str(tmp_path))
        store.set("a:x", 1)
        store.set("a:y", 2)
        all_keys: list[str] = store.keys()
        filtered: list[str] = store.keys("a:")
        assert len(filtered) >= 2
        assert "b:z" not in all_keys


# =============================================================================
# Core base
# =============================================================================


class ServiceHelper(Core):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.handled: list[Message] = []

    def handle(self, event: Message) -> None:
        self.handled.append(event)
        self.emit("response", {"received": event.event_type}, correlation_id=event.correlation_id)


class TestCore:
    def test_service_id(self) -> None:
        svc: ServiceHelper = ServiceHelper(name="mysvc", bus=LocalBus(), store=InMemory())
        assert svc.service_id == "mysvc"

    def test_identity_auto_created(self) -> None:
        svc: ServiceHelper = ServiceHelper(name="test", bus=LocalBus(), store=InMemory())
        assert svc.service_id == "test"
        sig: str = svc.sign_event("test_payload")
        assert len(sig) > 0

    def test_emit_publishes_event(self) -> None:
        bus: EventBus = LocalBus()
        received: list[Message] = []

        def handler(event: Message) -> None:
            received.append(event)

        bus.subscribe("custom.event", handler)
        svc: ServiceHelper = ServiceHelper(name="emitter", bus=bus, store=InMemory())
        svc.emit("custom.event", {"msg": "hello"})
        bus.start()
        time.sleep(0.01)
        assert len(received) == 1
        assert received[0].event_type == "custom.event"

    def test_event_has_signature(self) -> None:
        svc: ServiceHelper = ServiceHelper(name="signer", bus=LocalBus(), store=InMemory())
        event: Message = svc.emit("signed.event", {"data": 1})
        assert event.signature != ""

    def test_subscribe_receives_events(self) -> None:
        bus: EventBus = LocalBus()
        svc: ServiceHelper = ServiceHelper(name="subscriber", bus=bus, store=InMemory())
        svc.subscribe("incoming")
        bus.start()
        svc.start()
        bus.publish(Message(event_type="incoming", source="test"))
        time.sleep(0.01)
        assert len(svc.handled) == 1
        assert svc.handled[0].event_type == "incoming"

    def test_stop_unsubscribes(self) -> None:
        bus: EventBus = LocalBus()
        svc: ServiceHelper = ServiceHelper(name="stoppable", bus=bus, store=InMemory())
        svc.subscribe("incoming")
        svc.start()
        svc.stop()
        bus.start()
        bus.publish(Message(event_type="incoming", source="test"))
        time.sleep(0.01)
        assert len(svc.handled) == 0

    def test_dispatched_event_triggers_response(self) -> None:
        bus: EventBus = LocalBus()
        received: list[Message] = []

        def handler(event: Message) -> None:
            received.append(event)

        bus.subscribe("response", handler)
        svc: ServiceHelper = ServiceHelper(name="responder", bus=bus, store=InMemory())
        svc.subscribe("request")
        bus.start()
        svc.start()
        bus.publish(Message(event_type="request", source="test", correlation_id="corr-1"))
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
        received: list[Message] = []

        def handler(event: Message) -> None:
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

    def test_kyc_providers_round_trip(self) -> None:
        config: Configuration = Configuration.default()
        config.kyc_providers.pan_client_id = "pan-id"
        config.kyc_providers.pan_client_secret = "pan-secret"
        config.kyc_providers.pan_api_base_url = "https://api.karza.in"
        # Secret-shaped fields are redacted (popped) on to_dict
        # (save path); non-sensitive URL fields survive.
        d: dict = config.to_dict()
        assert "pan_client_id" not in d["kyc_providers"]
        assert "pan_client_secret" not in d["kyc_providers"]
        assert d["kyc_providers"]["pan_api_base_url"] == "https://api.karza.in"

    def test_dlq_health_check_registered(self) -> None:
        rt: Runtime = Runtime()
        status = rt.health.status()
        assert "dlq" in status["checks"]
        assert status["checks"]["dlq"]["ok"] is True
        assert "dead_letter_count" in status["checks"]["dlq"]

    def test_dlq_health_reflects_dead_letters(self) -> None:
        rt: Runtime = Runtime()
        bus = rt.bus
        bus.subscribe("fail.me", lambda e: (_ for _ in ()).throw(RuntimeError("bang")))
        bus.start()
        bus.publish(Message(event_type="fail.me", source="t"))
        status = rt.health.status()
        assert status["checks"]["dlq"]["dead_letter_count"] >= 1
