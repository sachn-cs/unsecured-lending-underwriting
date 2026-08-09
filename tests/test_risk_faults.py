"""Tests for residual-risk paths — silent-failure coverage."""

from __future__ import annotations

from typing import Any

import pytest

from underwrite.__bus__ import LocalBus
from underwrite.__events__ import Event, EventType
from underwrite.__store__ import MemoryStore
from underwrite.services.risk.handler import RiskHandler
from underwrite.services.risk.model import RiskModel


class EmitSpy:
    def __init__(self) -> None:
        self.captured: list[tuple[str | EventType, dict[str, Any]]] = []

    def __call__(self, event: Event) -> None:
        self.captured.append((event.event_type, event.payload))


class TestRiskServiceFaults:
    def test_model_failure_emits_sentinel_score(self) -> None:
        class FaultyModel:
            def predict(self, principal: float, term: float) -> float:
                raise RuntimeError("model crashed")

        bus = LocalBus()
        spy = EmitSpy()
        bus.subscribe(EventType.RISK_SCORED, spy)
        svc = RiskHandler(service_id="risk", bus=bus, store=MemoryStore())
        svc.set_model(FaultyModel())

        event = Event(
            event_type=EventType.LOAN_ORIGINATED,
            source="test",
            payload={
                "borrower": "user1",
                "principal": 50000,
                "term": 12,
                "default_probability": 0.02,
            },
        )
        svc.handle(event)
        risk_scored = [e for e in spy.captured if e[0] == EventType.RISK_SCORED]
        assert len(risk_scored) == 1
        assert risk_scored[0][1]["score"] == -1.0

    def test_early_warning_emitted_for_high_dp(self) -> None:
        bus = LocalBus()
        spy = EmitSpy()
        bus.subscribe(EventType.RISK_EARLY_WARNING, spy)
        svc = RiskHandler(service_id="risk", bus=bus, store=MemoryStore())

        event = Event(
            event_type=EventType.LOAN_ORIGINATED,
            source="test",
            payload={
                "borrower": "user1",
                "principal": 50000,
                "term": 12,
                "default_probability": 0.5,
            },
        )
        svc.handle(event)
        warnings = [e for e in spy.captured if e[0] == EventType.RISK_EARLY_WARNING]
        assert len(warnings) == 1


class TestAuditServiceFaults:
    def test_load_corrupted_jsonl_skips_bad_lines(self, tmp_path: Any) -> None:
        from underwrite.services.audit.handler import AuditHandler

        svc = AuditHandler(service_id="audit", bus=LocalBus(), store=MemoryStore())
        p = tmp_path / "audit.jsonl"
        p.write_text('{"event_type":"a","source":"s"}\nnot json\n{"event_type":"b","source":"s"}\n')
        svc.load_jsonl(str(p))
        assert len(svc.ledger) == 2
        assert svc.ledger[0]["event_type"] == "a"
        assert svc.ledger[1]["event_type"] == "b"

    def test_load_nonexistent_file_clears_ledger(self, tmp_path: Any) -> None:
        from underwrite.services.audit.handler import AuditHandler

        svc = AuditHandler(service_id="audit", bus=LocalBus(), store=MemoryStore())
        svc.handle(Event(event_type="test", source="test", payload={"dummy": True}))
        assert len(svc.ledger) == 1
        svc.load_jsonl(str(tmp_path / "nonexistent.jsonl"))
        assert len(svc.ledger) == 0


class TestValidationFaults:
    def test_require_finite_exception_chains_original_error(self) -> None:
        from underwrite.__exceptions__ import ProtocolError
        from underwrite.validate import require_finite

        with pytest.raises(ProtocolError) as exc_info:
            require_finite("not_a_number", "value")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ValueError | TypeError)

    def test_require_finite_preserves_value_type_in_chain(self) -> None:
        from underwrite.__exceptions__ import ProtocolError
        from underwrite.validate import require_finite

        with pytest.raises(ProtocolError) as exc_info:
            require_finite(None, "value")
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
