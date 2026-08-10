# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for residual-risk paths — silent-failure coverage."""

from __future__ import annotations

from typing import Any

import pytest

from underwrite.local import LocalBus
from underwrite.message import Message, Type
from underwrite.services.audit.handler import Handler as AuditHandler
from underwrite.services.risk.handler import Handler as RiskHandler
from underwrite.services.risk.model import RiskModel
from underwrite.store import InMemory


class EmitSpy:
    def __init__(self) -> None:
        self.captured: list[tuple[str | Type, dict[str, Any]]] = []

    def __call__(self, event: Message) -> None:
        self.captured.append((event.event_type, event.payload))


class TestRiskServiceFaults:
    def test_model_failure_emits_sentinel_score(self) -> None:
        class FaultyModel:
            def predict(self, principal: float, term: float) -> float:
                raise RuntimeError("model crashed")

        bus = LocalBus()
        spy = EmitSpy()
        bus.subscribe(Type.RISK_SCORED, spy)
        svc = RiskHandler(name="risk", bus=bus, store=InMemory())
        svc.set_model(FaultyModel())

        event = Message(
            event_type=Type.LOAN_ORIGINATED,
            source="test",
            payload={
                "borrower": "user1",
                "principal": 50000,
                "term": 12,
                "default_probability": 0.02,
            },
        )
        svc.handle(event)
        risk_scored = [e for e in spy.captured if e[0] == Type.RISK_SCORED]
        assert len(risk_scored) == 1
        assert risk_scored[0][1]["score"] == -1.0

    def test_early_warning_emitted_for_high_dp(self) -> None:
        bus = LocalBus()
        spy = EmitSpy()
        bus.subscribe(Type.RISK_EARLY_WARNING, spy)
        svc = RiskHandler(name="risk", bus=bus, store=InMemory())

        event = Message(
            event_type=Type.LOAN_ORIGINATED,
            source="test",
            payload={
                "borrower": "user1",
                "principal": 50000,
                "term": 12,
                "default_probability": 0.5,
            },
        )
        svc.handle(event)
        warnings = [e for e in spy.captured if e[0] == Type.RISK_EARLY_WARNING]
        assert len(warnings) == 1


class TestAuditServiceFaults:
    def test_load_corrupted_jsonl_skips_bad_lines(self, tmp_path: Any) -> None:
        svc = AuditHandler(name="audit", bus=LocalBus(), store=InMemory())
        p = tmp_path / "audit.jsonl"
        p.write_text('{"event_type":"a","source":"s"}\nnot json\n{"event_type":"b","source":"s"}\n')
        svc.load_jsonl(str(p))
        assert len(svc.ledger) == 2
        assert svc.ledger[0]["event_type"] == "a"
        assert svc.ledger[1]["event_type"] == "b"

    def test_load_nonexistent_file_clears_ledger(self, tmp_path: Any) -> None:
        svc = AuditHandler(name="audit", bus=LocalBus(), store=InMemory())
        svc.handle(Message(event_type="test", source="test", payload={"dummy": True}))
        assert len(svc.ledger) == 1
        svc.load_jsonl(str(tmp_path / "nonexistent.jsonl"))
        assert len(svc.ledger) == 0


class TestValidationFaults:
    def test_require_finite_exception_chains_original_error(self) -> None:
        from underwrite.exceptions import ProtocolError
        from underwrite.validate import PayloadValidator

        with pytest.raises(ProtocolError) as exc_info:
            PayloadValidator.require_finite("not_a_number", "value")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError | TypeError)

    def test_require_finite_preserves_value_type_in_chain(self) -> None:
        from underwrite.exceptions import ProtocolError
        from underwrite.validate import PayloadValidator

        with pytest.raises(ProtocolError) as exc_info:
            PayloadValidator.require_finite(None, "value")
        assert exc_info.value.__cause__ is not None
        assert "NoneType" in str(exc_info.value)


class TestRiskModelFaults:
    def test_model_no_joblib_fallback_to_json(self, tmp_path: Any) -> None:
        import hashlib
        import json

        model_path = str(tmp_path / "model.json")
        content = {"coef_": [5e-7, 0.01], "intercept_": 0.02}
        with open(model_path, "w") as fh:
            json.dump(content, fh)
        sha = hashlib.sha256(open(model_path, "rb").read()).hexdigest()
        with open(str(tmp_path / "model.json.sha256"), "w") as fh:
            fh.write(sha)
        rm = RiskModel(model_path)
        assert rm is not None
        result = rm.predict(100_000, 12)
        assert 0.0 <= result <= 1.0

    def test_model_empty_path_uses_heuristic(self) -> None:
        rm = RiskModel(model_path="")
        result = rm.predict(100_000, 12)
        assert 0.0 <= result <= 1.0

    def test_model_nonexistent_path_uses_heuristic(self) -> None:
        rm = RiskModel(model_path="/nonexistent/model.pkl")
        result = rm.predict(100_000, 12)
        assert 0.0 <= result <= 1.0
