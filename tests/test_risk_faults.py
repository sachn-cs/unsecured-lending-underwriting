"""Tests for residual-risk paths — silent-failure coverage."""

from __future__ import annotations

from typing import Any

from underwrite.__events__ import Event, EventType
from underwrite.services.risk.model import RiskModel
from underwrite.services.risk.service import RiskService


class TestRiskServiceFaults:

    def test_model_failure_emits_sentinel_score(self) -> None:
        emitted: list = []

        class FaultyModel:

            def predict(self, principal: float, term: float) -> float:
                raise RuntimeError("model crashed")

        svc = RiskService(service_id="risk")
        svc.set_model(FaultyModel())

        def capture(event_type: str,
                    payload: dict[str, Any],
                    correlation_id: str = "") -> None:
            emitted.append((event_type, payload))

        svc.emit = capture
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
        risk_scored = [e for e in emitted if e[0] == EventType.RISK_SCORED]
        assert len(risk_scored) == 1
        assert risk_scored[0][1]["score"] == -1.0

    def test_early_warning_emitted_for_high_dp(self) -> None:
        emitted: list = []

        svc = RiskService(service_id="risk")

        def capture(event_type: str,
                    payload: dict[str, Any],
                    correlation_id: str = "") -> None:
            emitted.append((event_type, payload))

        svc.emit = capture
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
        warnings = [e for e in emitted if e[0] == EventType.RISK_EARLY_WARNING]
        assert len(warnings) == 1


class TestAuditServiceFaults:

    def test_load_corrupted_jsonl_skips_bad_lines(self, tmp_path: Any) -> None:
        from underwrite.services.audit.service import AuditService
        svc = AuditService(service_id="audit")
        p = tmp_path / "audit.jsonl"
        p.write_text('{"event_type":"a","source":"s"}\n'
                     'not json\n'
                     '{"event_type":"b","source":"s"}\n')
        svc.load_jsonl(str(p))
        assert len(svc.ledger) == 2
        assert svc.ledger[0]["event_type"] == "a"
        assert svc.ledger[1]["event_type"] == "b"

    def test_load_nonexistent_file_clears_ledger(self, tmp_path: Any) -> None:
        from underwrite.services.audit.service import AuditService
        svc = AuditService(service_id="audit")
        svc.handle(
            Event(event_type="test", source="test", payload={"dummy": True}))
        assert len(svc.ledger) == 1
        svc.load_jsonl(str(tmp_path / "nonexistent.jsonl"))
        assert len(svc.ledger) == 0


class TestValidationFaults:

    def test_require_finite_exception_chains_original_error(self) -> None:
        from underwrite.__exceptions__ import ProtocolError
        from underwrite.validate import require_finite
        try:
            require_finite("not_a_number", "value")
        except ProtocolError as exc:
            assert exc.__cause__ is not None
            assert isinstance(exc.__cause__, (ValueError, TypeError))

    def test_require_finite_preserves_value_type_in_chain(self) -> None:
        from underwrite.__exceptions__ import ProtocolError
        from underwrite.validate import require_finite
        try:
            require_finite(None, "value")
        except ProtocolError as exc:
            assert exc.__cause__ is not None
            assert "NoneType" in str(exc)


class TestRiskModelFaults:

    def test_model_no_joblib_fallback_to_json(self, tmp_path: Any) -> None:
        import json
        model_path = str(tmp_path / "model.json")
        with open(model_path, "w") as fh:
            json.dump({"coef_": [5e-7, 0.01], "intercept_": 0.02}, fh)
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
