"""Auth tests for the admin graph-mutation endpoints (Phase 9).

POST /admin/api/node|edge require the ``X-API-Key`` header to match
``$ADMIN_API_KEY``; GET endpoints stay public. Gated on FastAPI/httpx so they
run in CI and skip cleanly offline. No real network (monkeypatch env only).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402

_NODE = {"node_id": "n1", "type": "topic", "name": "N1", "weight": 1.0}
_EDGE = {"from_node": "a", "to_node": "b", "relation_type": "related_to", "weight": 0.5}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A real (sqlite) DB so an authorised write reaches the 201 path.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    with TestClient(create_app()) as c:
        yield c


@pytest.mark.unit
def test_post_node_without_key_returns_422(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "k")
    assert client.post("/admin/api/node", json=_NODE).status_code == 422


@pytest.mark.unit
def test_post_edge_without_key_returns_422(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "k")
    assert client.post("/admin/api/edge", json=_EDGE).status_code == 422


@pytest.mark.unit
def test_post_node_wrong_key_returns_401(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right")
    resp = client.post("/admin/api/node", json=_NODE, headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_post_node_no_key_configured_returns_503(client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    # Header present so we pass FastAPI validation and reach the 503 branch.
    resp = client.post("/admin/api/node", json=_NODE, headers={"X-API-Key": "anything"})
    assert resp.status_code == 503


@pytest.mark.unit
def test_post_node_correct_key_returns_201(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right")
    resp = client.post("/admin/api/node", json=_NODE, headers={"X-API-Key": "right"})
    assert resp.status_code == 201
    assert resp.json()["node_id"] == "n1"


@pytest.mark.unit
def test_get_endpoints_require_no_auth(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "right")
    assert client.get("/admin/api/graph").status_code == 200
    assert client.get("/admin/api/stats").status_code == 200
    assert client.get("/admin/").status_code == 200
