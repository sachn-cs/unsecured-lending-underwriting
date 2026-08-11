# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Error-path tests for narrowed exception blocks — graceful degradation checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from helpers import BadStr, BrokenStore, ConcreteService, RaisingStrategy

from underwrite.bus import EventBus
from underwrite.config import AuthzConfig, Configuration
from underwrite.exceptions import ProtocolError
from underwrite.local import LocalBus
from underwrite.message import Message
from underwrite.runtime import Runtime, build_authz
from underwrite.services.audit import Handler as AuditHandler
from underwrite.services.mechanism import Handler as MechanismHandler
from underwrite.services.risk.model import RiskModel, RiskScoringStrategy
from underwrite.store import Sqlite, Store


class TestSafeStoreGet:
    def test_returns_default_on_exception(self) -> None:
        svc = ConcreteService(name="test_svc_get", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.store = cast(Store, BrokenStore())
        result = svc.safe_store_get("some_key", default="fallback")
        assert result == "fallback"

    def test_returns_store_result_for_missing_key(self) -> None:
        svc = ConcreteService(name="test_svc_get_missing", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.store = Sqlite(":memory:")
        result = svc.safe_store_get("missing", default=42)
        assert result is None


class TestSafeStoreSet:
    def test_returns_false_on_exception(self) -> None:
        svc = ConcreteService(name="test_svc_set", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.store = cast(Store, BrokenStore())
        result = svc.safe_store_set("some_key", "value")
        assert result is False


class TestRiskModelPredictFallback:
    def test_falls_back_on_strategy_exception(self) -> None:
        model = RiskModel()
        model.strategy = cast(RiskScoringStrategy, RaisingStrategy())
        score = model.predict(10000.0, 12.0)
        assert 0.0 <= score <= 1.0

    def test_falls_back_for_extreme_input(self) -> None:
        model = RiskModel()
        model.strategy = cast(RiskScoringStrategy, RaisingStrategy())
        score = model.predict(float("nan"), 12.0)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


class TestBusSyncDispatchDLQ:
    def test_handler_failure_sends_to_dlq(self) -> None:
        bus: EventBus | LocalBus = LocalBus()
        bus.subscribe("test.event", lambda e: (_ for _ in ()).throw(ValueError("fail")))
        bus.start()
        event = Message(event_type="test.event", source="test", payload={})
        bus.publish(event)
        assert bus.dlq.count > 0

    def test_dlq_contains_event_after_handler_failure(self) -> None:
        bus: EventBus | LocalBus = LocalBus()
        bus.subscribe("test.event3", lambda e: (_ for _ in ()).throw(ValueError("fail")))
        bus.start()
        event = Message(event_type="test.event3", source="test", payload={})
        bus.publish(event)
        assert bus.dlq.count > 0


class TestConfigSkipBadFile:
    def test_returns_default_on_nonexistent_path(self) -> None:
        config = Configuration.load(path="/nonexistent/config.json")
        assert isinstance(config, Configuration)

    def test_returns_default_on_malformed_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad_config.json"
        bad_file.write_text("{invalid json")
        config = Configuration.load(path=str(bad_file))
        assert isinstance(config, Configuration)


class TestEventNonSerializablePayload:
    def test_raises_protocol_error_on_bad_payload(self) -> None:
        with pytest.raises(ProtocolError, match="MAX_PAYLOAD_SIZE"):
            Message(
                event_type="test.bad",
                source="test",
                payload={"bad": BadStr()},
            )


class TestAuthzBuildFallback:
    def test_returns_none_on_malformed_policy_file(self, tmp_path: Path) -> None:
        bad_policy = tmp_path / "policy.json"
        bad_policy.write_text("{bad json")
        config = Configuration(authz=AuthzConfig(enabled=True, policy_file=str(bad_policy)))
        rt = Runtime(config=config)
        result = build_authz(rt.config.authz)
        assert result is None

    def test_returns_none_on_missing_policy_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent" / "policy.json"
        config = Configuration(authz=AuthzConfig(enabled=True, policy_file=str(missing)))
        rt = Runtime(config=config)
        result = build_authz(rt.config.authz)
        assert result is not None


class TestSqliteHealthFallback:
    def test_health_returns_false_on_corrupted_file(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.db"
        path.write_bytes(b"not a sqlite database at all")
        store = Sqlite(path=str(path))
        result = store.health()
        assert result["ok"] is False
        assert "detail" in result


class TestMechanismRejection:
    def test_repay_unknown_user_emits_rejected(self) -> None:
        bus: EventBus | LocalBus = LocalBus()
        bus.start()
        svc = MechanismHandler(name="mechanism", bus=bus, store=Sqlite(":memory:"))
        emitted: list[Message] = []

        def capture(e: Message) -> None:
            emitted.append(e)

        bus.subscribe("mechanism.rejected", capture)
        event = Message(
            event_type="mechanism",
            source="test",
            payload={"command": "repay", "user": "nobody", "amount": 100.0},
        )
        svc.handle(event)
        assert len(emitted) >= 1


class TestAuditLoadJsonl:
    def test_skips_corrupted_line(self, tmp_path: Path) -> None:
        ledger_file = tmp_path / "audit.jsonl"
        ledger_file.write_text('{"valid": true}\nnot json\n{"also_valid": 42}\n')
        svc = AuditHandler(name="audit", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.load_jsonl(str(ledger_file))
        records = svc.ledger
        assert len(records) == 2
        assert records[0] == {"valid": True}
        assert records[1] == {"also_valid": 42}

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        ledger_file = tmp_path / "empty.jsonl"
        ledger_file.write_text("")
        svc = AuditHandler(name="audit", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.load_jsonl(str(ledger_file))
        records = svc.ledger
        assert len(records) == 0

    def test_handles_missing_file(self) -> None:
        svc = AuditHandler(name="audit", bus=LocalBus(), store=Sqlite(":memory:"))
        svc.load_jsonl("/nonexistent/audit.jsonl")
        records = svc.ledger
        assert len(records) == 0


class TestLoadStrategyFallback:
    def test_load_strategy_uses_json(self, tmp_path: Path) -> None:
        model_file = tmp_path / "model.json"
        params = {"weights": [0.3, 0.7], "bias": 0.1}
        model_file.write_text(json.dumps(params))
        strategy = RiskModel.load_strategy(str(model_file))
        assert strategy is not None
        score = strategy.predict(10000.0, 12.0)
        assert 0.0 <= score <= 1.0

    def test_load_strategy_raises_on_bad_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        with pytest.raises(ValueError):
            RiskModel.load_strategy(str(bad_file))

    def test_load_strategy_raises_on_missing_file(self) -> None:
        with pytest.raises(ValueError):
            RiskModel.load_strategy("/nonexistent/model.joblib")
