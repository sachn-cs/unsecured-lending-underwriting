from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from ulu.api.app import app, service
from ulu.audit import AppendOnlyLedger

client = TestClient(app)

_ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token"}


def reset_service() -> None:
    service.ledger = AppendOnlyLedger()
    service.engine = service.engine.__class__(ledger=service.ledger)


def test_append_only_ledger_round_trip(tmp_path: Path):
    ledger = AppendOnlyLedger()
    ledger.append("evt1", {"a": 1})
    ledger.append("evt2", {"b": 2})

    p = tmp_path / "audit.jsonl"
    ledger.save_jsonl(p)
    restored = AppendOnlyLedger.load_jsonl(p)

    events = restored.events()
    assert len(events) == 2
    assert events[0].seq == 1
    assert events[1].seq == 2
    assert events[1].event_type == "evt2"


def test_api_end_to_end_and_ledger(monkeypatch, tmp_path: Path):
    reset_service()
    monkeypatch.setenv("ULU_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("ULU_DATA_DIR", str(tmp_path))

    assert client.get("/health").status_code == 200

    assert client.post("/seed", json={"user": "s", "base_budget": 100.0}).status_code == 200
    assert (
        client.post(
            "/user",
            json={
                "sponsor": "s",
                "user": "a",
                "delegation_amount": 50.0,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/user",
            json={
                "sponsor": "a",
                "user": "b",
                "delegation_amount": 20.0,
            },
        ).status_code
        == 200
    )

    q = client.post(
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
    assert q.status_code == 200
    assert q.json()["total_interest"] > 0

    o = client.post(
        "/originate",
        json={
            "borrower": "b",
            "principal": 5.0,
            "term": 1.0,
            "default_probability": 0.2,
            "protocol_rate": 0.3,
            "max_delegation_rate": 0.1,
        },
    )
    assert o.status_code == 200

    assert client.post("/repay", json={"user": "b", "delta_earned": 1.0}).status_code == 200

    state = client.get("/state").json()

    assert client.post("/state/save", json={"path": "state.json"}).status_code == 200
    assert client.post("/ledger/save", json={"path": "ledger.jsonl"}).status_code == 200

    assert client.post("/state/load", json={"path": "state.json"}).status_code == 200
    assert client.post("/ledger/load", json={"path": "ledger.jsonl"}).status_code == 200

    ledger_resp = client.get("/ledger")
    assert ledger_resp.status_code == 200
    events = ledger_resp.json()["events"]
    assert len(events) >= 5
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)

    assert "state" in state


def test_path_traversal_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ULU_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("ULU_DATA_DIR", str(tmp_path))
    reset_service()

    resp = client.post("/state/save", json={"path": "../../../etc/passwd"})
    assert resp.status_code == 400
    assert "invalid path" in resp.json()["detail"]


def test_api_validation_error_maps_to_400():
    reset_service()
    assert client.post("/seed", json={"user": "s", "base_budget": 100.0}).status_code == 200
    bad = client.post(
        "/user",
        json={"sponsor": "ghost", "user": "x", "delegation_amount": 1.0},
    )
    assert bad.status_code == 400


def test_api_ready_and_metrics_endpoints():
    reset_service()
    ready = client.get("/ready")
    assert ready.status_code == 503

    client.post("/seed", json={"user": "s", "base_budget": 100.0})
    ready = client.get("/ready")
    assert ready.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "ulu_requests_total" in metrics.text


def test_idempotent_mutation_replay_and_conflict():
    reset_service()
    headers = {"Idempotency-Key": "seed-1"}
    payload = {"user": "s", "base_budget": 100.0}

    first = client.post("/seed", json=payload, headers=headers)
    assert first.status_code == 200

    second = client.post("/seed", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json() == first.json()

    conflict = client.post(
        "/seed",
        json={"user": "s2", "base_budget": 100.0},
        headers=headers,
    )
    assert conflict.status_code == 409


def test_admin_reset_requires_auth(monkeypatch):
    monkeypatch.setenv("ULU_ADMIN_TOKEN", "")
    reset_service()
    resp = client.post("/admin/reset")
    assert resp.status_code == 503


def test_admin_endpoints_and_reset(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ULU_ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("ULU_DATA_DIR", str(tmp_path))
    reset_service()
    client.post("/seed", json={"user": "s", "base_budget": 100.0})
    client.post(
        "/user",
        json={"sponsor": "s", "user": "a", "delegation_amount": 20.0},
    )

    graph = client.get("/admin/graph", headers=_ADMIN_HEADERS)
    assert graph.status_code == 200
    assert graph.json()["seeds"] == ["s"]

    util = client.get("/admin/utilization", headers=_ADMIN_HEADERS)
    assert util.status_code == 200
    assert "delegation_utilization" in util.json()

    solvency = client.get("/admin/solvency", headers=_ADMIN_HEADERS)
    assert solvency.status_code == 200
    assert solvency.json()["invariants"] == "ok"

    reset = client.post("/admin/reset", headers=_ADMIN_HEADERS)
    assert reset.status_code == 200
    assert client.get("/admin/graph", headers=_ADMIN_HEADERS).json()["seeds"] == []
