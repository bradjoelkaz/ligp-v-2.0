"""Tests for health-check logic (Phase 12).

The logic in :mod:`api.health_checks` is framework-free and tested offline
against SQLite (and a postgres URL, which is "disconnected" since psycopg is not
installed). Endpoint status-code tests are gated on FastAPI.
"""

from __future__ import annotations

import pytest

from api import health_checks


@pytest.mark.unit
def test_check_database_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert health_checks.check_database() == "not_configured"


@pytest.mark.unit
def test_check_database_connected_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'h.db'}")
    assert health_checks.check_database() == "connected"


@pytest.mark.unit
def test_check_database_disconnected(monkeypatch):
    # Postgres URL with psycopg unavailable -> connection error -> disconnected.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5/none")
    assert health_checks.check_database() == "disconnected"


@pytest.mark.unit
def test_check_metrics_returns_known_state():
    assert health_checks.check_metrics() in ("enabled", "disabled")


@pytest.mark.unit
def test_health_report_healthy_without_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    body, healthy = health_checks.health_report()
    assert healthy is True
    assert body["status"] == "healthy"
    assert body["components"]["database"] == "not_configured"
    assert "timestamp" in body


@pytest.mark.unit
def test_health_report_unhealthy_when_db_down(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5/none")
    body, healthy = health_checks.health_report()
    assert healthy is False
    assert body["status"] == "unhealthy"
    assert body["components"]["database"] == "disconnected"


# -- endpoint status codes (require FastAPI) ---------------------------------
@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("jinja2")
    from fastapi.testclient import TestClient

    from api.main import create_app

    return TestClient(create_app())


@pytest.mark.unit
def test_health_endpoint_200_without_db(client, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.unit
def test_health_endpoint_200_with_sqlite(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'h.db'}")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["components"]["database"] == "connected"


@pytest.mark.unit
def test_health_endpoint_503_when_db_down(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5/none")
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["components"]["database"] == "disconnected"
