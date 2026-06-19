"""End-to-end flows (Phase 13).

Drives the real FastAPI app + raw-SQL repositories + pipeline together against a
temporary SQLite DB (offline; no external infra). Gated on the web stack so it
skips cleanly where FastAPI/httpx are absent and runs fully in CI.

Scenarios:
  1. Content lifecycle: generate (async) -> status completed -> history -> stats
  2. Pipeline -> graph DB persistence -> admin D3 graph endpoint
  3. Admin auth (X-API-Key) + CORS preflight
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'e2e.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


# --------------------------------------------------------------------------
# Scenario 1: content generation lifecycle
# --------------------------------------------------------------------------
@pytest.mark.e2e
def test_content_lifecycle(db_url):
    with TestClient(create_app()) as client:
        gen = client.post("/content/generate", json={"node_id": "topic:ai", "name": "AI"})
        assert gen.status_code == 200
        body = gen.json()
        assert body["status"] == "pending"
        cid = body["content_id"]

        # TestClient runs the BackgroundTask synchronously, so it is resolved.
        status = None
        for _ in range(5):
            status = client.get(f"/content/status/{cid}").json()
            if status["status"] in ("completed", "failed"):
                break
        assert status["status"] == "completed"
        assert status["result"] is not None

        history = client.get("/content/history").json()
        assert any(row["content_id"] == cid for row in history)

        stats = client.get("/admin/api/content-stats").json()
        assert stats["total"] >= 1


# --------------------------------------------------------------------------
# Scenario 2: pipeline -> graph DB -> admin graph
# --------------------------------------------------------------------------
@pytest.mark.e2e
def test_pipeline_persists_graph_to_admin(db_url):
    from database.db_adapter import DBAdapter
    from database.repositories.graph_repo import GraphRepository
    from orchestration.flows.daily_pipeline import run_daily_pipeline

    docs = [{"source_id": "e2e-1", "title": "Quantum Computing", "text": "qubits and gates"}]
    summary = run_daily_pipeline(documents=docs)
    assert summary["graph_nodes"] >= 12

    repo = GraphRepository(DBAdapter(db_url))
    try:
        db_nodes, _ = repo.counts()
    finally:
        repo.db.close()
    assert db_nodes >= 12  # pipeline persisted the graph

    with TestClient(create_app()) as client:
        payload = client.get("/admin/api/graph").json()
        # Admin graph is served from the DB (not the seed) and matches it.
        assert len(payload["nodes"]) == db_nodes
        assert any(n["type"] == "topic" for n in payload["nodes"])


# --------------------------------------------------------------------------
# Scenario 3: admin auth + CORS
# --------------------------------------------------------------------------
@pytest.mark.e2e
def test_admin_auth_and_cors(db_url, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "e2e-secret")
    node = {"node_id": "n1", "type": "topic", "name": "N1", "weight": 1.0}
    with TestClient(create_app()) as client:
        # Missing key -> 422 (required header); wrong key -> 401.
        assert client.post("/admin/api/node", json=node).status_code == 422
        wrong = client.post("/admin/api/node", json=node, headers={"X-API-Key": "nope"})
        assert wrong.status_code == 401
        # Correct key -> 201.
        ok = client.post("/admin/api/node", json=node, headers={"X-API-Key": "e2e-secret"})
        assert ok.status_code == 201

        # CORS preflight on a public route returns the allow-origin header.
        pre = client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert pre.status_code in (200, 204)
        assert "access-control-allow-origin" in {k.lower() for k in pre.headers}
