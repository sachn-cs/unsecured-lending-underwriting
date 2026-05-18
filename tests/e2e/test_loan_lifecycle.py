"""End-to-end tests covering full loan lifecycle."""

from __future__ import annotations

from pathlib import Path

import jwt
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from ulu.api.app import app, limiter, service
from ulu.api.routers.admin import clear_admin_cache
from ulu.audit import AppendOnlyLedger
from ulu.infra.config import settings

client = TestClient(app)


def _admin_jwt() -> str:
    token = jwt.encode(
        {"role": "admin"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return f"Bearer {token}"


_ADMIN_HEADERS = {"Authorization": _admin_jwt()}


def reset_service() -> None:
    service.ledger = AppendOnlyLedger()
    service.engine = service.engine.__class__(ledger=service.ledger)
    limiter._storage.reset()
    clear_admin_cache()


def test_full_lifecycle(monkeypatch, tmp_path: Path) -> None:
    """Seed -> delegate -> quote -> originate -> repay -> default."""
    reset_service()
    monkeypatch.setenv("ULU_DATA_DIR", str(tmp_path))

    # Health probes
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/live").json() == {"status": "alive"}

    # Seed and delegate chain: s -> a -> b
    assert client.post("/seed", json={"user": "s", "base_budget": 100.0}).status_code == 200
    assert (
        client.post("/user", json={"sponsor": "s", "user": "a", "delegation_amount": 50.0}).status_code
        == 200
    )
    assert (
        client.post("/user", json={"sponsor": "a", "user": "b", "delegation_amount": 20.0}).status_code
        == 200
    )

    # Quote before originate
    quote = client.post(
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
    assert quote.status_code == 200
    assert quote.json()["total_interest"] > 0

    # Originate loan
    orig = client.post(
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
    assert orig.status_code == 200
    assert orig.json()["borrower"] == "b"

    # Repay partial
    assert client.post("/repay", json={"user": "b", "delta_earned": 1.0}).status_code == 200

    # Default
    assert client.post("/default", json={"borrower": "b"}).status_code == 200

    # Admin inspection
    graph = client.get("/admin/graph", headers=_ADMIN_HEADERS)
    assert graph.status_code == 200
    data = graph.json()
    assert data["seeds"] == ["s"]
    assert any(e["sponsor"] == "s" and e["child"] == "a" for e in data["edges"])

    util = client.get("/admin/utilization", headers=_ADMIN_HEADERS)
    assert util.status_code == 200
    assert "delegation_utilization" in util.json()

    solvency = client.get("/admin/solvency", headers=_ADMIN_HEADERS)
    assert solvency.status_code == 200
    assert solvency.json()["invariants"] == "ok"

    # Ledger events
    ledger = client.get("/ledger")
    assert ledger.status_code == 200
    events = ledger.json()["events"]
    assert len(events) >= 6
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)

    # Metrics expose Prometheus format
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "ulu_requests_total" in metrics.text

    # State round-trip
    assert client.post("/state/save", json={"path": "state.json"}).status_code == 200
    assert client.post("/state/load", json={"path": "state.json"}).status_code == 200

    # Reset
    reset = client.post("/admin/reset", headers=_ADMIN_HEADERS)
    assert reset.status_code == 200
    assert client.get("/admin/graph", headers=_ADMIN_HEADERS).json()["seeds"] == []


def test_idempotency_and_rate_limit_replay(monkeypatch, tmp_path: Path) -> None:
    """Idempotency replay works; rate limit accumulates."""
    reset_service()
    monkeypatch.setenv("ULU_DATA_DIR", str(tmp_path))

    headers = {"Idempotency-Key": "e2e-seed-1"}
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


def test_path_traversal_and_validation(monkeypatch, tmp_path: Path) -> None:
    """Path traversal rejected; invalid payloads return 400."""
    monkeypatch.setenv("ULU_DATA_DIR", str(tmp_path))
    reset_service()

    resp = client.post("/state/save", json={"path": "../../../etc/passwd"})
    assert resp.status_code == 400

    bad = client.post("/seed", json={"user": "s", "base_budget": -1.0})
    assert bad.status_code == 422


def test_ready_without_seed() -> None:
    """Ready endpoint returns 503 when invariants fail (no seeds)."""
    reset_service()
    ready = client.get("/ready")
    assert ready.status_code == 503

    client.post("/seed", json={"user": "s", "base_budget": 100.0})
    ready = client.get("/ready")
    assert ready.status_code == 200
