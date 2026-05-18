"""Unit tests for bulk operations API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ulu.api.app import app

client = TestClient(app)


class TestBulkApi:
    def test_bulk_create_seeds(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_DATA_DIR", "/tmp/ulu_bulk_test")
        payload = [
            {"user": "s1", "base_budget": 100.0},
            {"user": "s2", "base_budget": 200.0},
        ]
        response = client.post("/bulk/seeds", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["created"]) == 2
        assert data["errors"] == []

    def test_bulk_create_users(self, monkeypatch) -> None:
        monkeypatch.setenv("ULU_DATA_DIR", "/tmp/ulu_bulk_test")
        client.post("/seed", json={"user": "seed", "base_budget": 1000.0})
        payload = [
            {"sponsor": "seed", "user": "a", "delegation_amount": 100.0},
            {"sponsor": "seed", "user": "b", "delegation_amount": 50.0},
        ]
        response = client.post("/bulk/users", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["created"]) == 2
