"""Unit tests for API versioning middleware."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ulu.api.versioning import VersioningMiddleware

app = FastAPI()
app.add_middleware(VersioningMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class TestVersioningMiddleware:
    def test_v1_prefix(self) -> None:
        client = TestClient(app)
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["X-API-Version"] == "v1"

    def test_v2_prefix(self) -> None:
        client = TestClient(app)
        response = client.get("/v2/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["X-API-Version"] == "v2"

    def test_no_prefix_defaults_v1(self) -> None:
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers["X-API-Version"] == "v1"

    def test_unsupported_prefix_returns_404(self) -> None:
        client = TestClient(app)
        response = client.get("/v3/health")
        assert response.status_code == 404
        assert response.headers["X-API-Version"] == "v1"
