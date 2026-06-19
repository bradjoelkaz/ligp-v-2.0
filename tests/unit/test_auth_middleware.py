"""Unit tests for the API key authentication middleware (Phase 9 / DD-012)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.middleware.auth as auth_mod  # noqa: E402
from api.middleware.auth import APIKeyMiddleware  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_key_cache():
    """Reset the cached API key before and after each test to avoid leakage."""
    auth_mod._API_KEY = None
    yield
    auth_mod._API_KEY = None


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/data")
    def data() -> dict[str, list[int]]:
        return {"data": [1, 2, 3]}

    app.add_middleware(APIKeyMiddleware)
    return app


@pytest.mark.unit
def test_public_routes_bypass_auth(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "secret123")
    client = TestClient(_make_app())
    assert client.get("/health").status_code == 200


@pytest.mark.unit
def test_protected_route_requires_key(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "secret123")
    client = TestClient(_make_app())
    assert client.get("/api/data").status_code == 401


@pytest.mark.unit
def test_protected_route_with_valid_key(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "secret123")
    client = TestClient(_make_app())
    resp = client.get("/api/data", headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200
    assert resp.json() == {"data": [1, 2, 3]}


@pytest.mark.unit
def test_protected_route_with_invalid_key(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "secret123")
    client = TestClient(_make_app())
    assert client.get("/api/data", headers={"X-API-Key": "wrong"}).status_code == 401


@pytest.mark.unit
def test_no_key_configured_allows_all(monkeypatch):
    monkeypatch.delenv("API_SECRET_KEY", raising=False)
    client = TestClient(_make_app())
    assert client.get("/api/data").status_code == 200
