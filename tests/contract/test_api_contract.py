"""Lightweight consumer-provider contract tests.

Item 71 from production roadmap.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ulu.api.app import app


class TestApiContract:
    def test_openapi_spec_has_required_paths(self) -> None:
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        paths = spec.get("paths", {})
        required = ["/health", "/ready", "/seed", "/user", "/quote", "/originate", "/repay", "/default", "/ledger"]
        for path in required:
            assert path in paths, f"missing required path: {path}"

    def test_openapi_spec_has_response_models(self) -> None:
        client = TestClient(app)
        spec = client.get("/openapi.json").json()
        schemas = spec.get("components", {}).get("schemas", {})
        required_models = ["HealthResponse", "QuoteResponse", "OriginateResponse"]
        for model in required_models:
            assert model in schemas, f"missing required schema: {model}"

    def test_health_contract(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] == "ok"

    def test_quote_contract(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_DATA_DIR", "/tmp/ulu_contract_test")
        client = TestClient(app)
        client.post("/seed", json={"user": "s", "base_budget": 100.0})
        client.post("/user", json={"sponsor": "s", "user": "b", "delegation_amount": 50.0})
        resp = client.post(
            "/quote",
            json={
                "borrower": "b",
                "principal": 5.0,
                "term": 1.0,
                "default_probability": 0.2,
                "protocol_rate": 0.3,
                "max_delegation_rate": 0.1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "borrower" in data
        assert "principal" in data
        assert "total_interest" in data
        assert "delegation_utilization" in data

    def test_error_contract(self) -> None:
        client = TestClient(app)
        resp = client.get("/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
