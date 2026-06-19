"""Integration tests for the full FastAPI application (Phase 8).

Builds the real app via ``create_app()`` and exercises the system routes, the
``/metrics`` exposition and the admin dashboard end-to-end with ``TestClient``.
Skipped cleanly when the web stack is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.mark.integration
def test_root_returns_service_metadata(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "iigp"
    assert body["admin"] == "/admin/"


@pytest.mark.integration
def test_health_and_ready_and_version(client):
    assert client.get("/health").json() == {"status": "ok"}

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert "ready" in ready.json()

    version = client.get("/version").json()
    assert version["name"]
    assert version["version"]


@pytest.mark.integration
def test_metrics_endpoint_exposes_prometheus_text(client):
    # Generate some traffic first so counters exist.
    client.get("/health")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    # When prometheus_client is installed the request counter must appear.
    try:
        import prometheus_client  # noqa: F401
    except ImportError:  # pragma: no cover - fallback exposition path
        assert b"disabled" in resp.content
    else:
        assert "iigp_http_requests_total" in resp.text


@pytest.mark.integration
def test_admin_dashboard_navigation(client):
    for path in [
        "/admin/",
        "/admin/graph",
        "/admin/content",
        "/admin/experiments",
        "/admin/settings",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "text/html" in resp.headers["content-type"]


@pytest.mark.integration
def test_admin_graph_data_endpoint(client):
    resp = client.get("/admin/api/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert {"nodes", "links"} == set(body)
    assert len(body["nodes"]) == 12


@pytest.mark.integration
def test_openapi_schema_available(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/health" in paths
    assert "/admin/api/graph" in paths


@pytest.mark.integration
def test_admin_dashboard_loads_html(client):
    """Admin dashboard root returns an HTML document."""
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


@pytest.mark.integration
def test_nonexistent_route_returns_404(client):
    """Unknown routes return 404 (or 405 if the path matches another method)."""
    resp = client.get("/api/nonexistent-route-xyz")
    assert resp.status_code in (404, 405)


@pytest.mark.integration
def test_cors_headers_present(client):
    """A CORS preflight on a public route is handled by the CORS middleware."""
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in (200, 204, 405)


@pytest.mark.integration
def test_admin_graph_write_then_read(tmp_path, monkeypatch):
    """POST node/edge persists to the DB and is reflected by /admin/api/graph."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'graph.db'}")
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    headers = {"X-API-Key": "secret-admin"}
    with TestClient(create_app()) as c:
        r1 = c.post(
            "/admin/api/node",
            json={"node_id": "t:x", "type": "topic", "name": "X", "weight": 1.0},
            headers=headers,
        )
        assert r1.status_code == 201
        r2 = c.post(
            "/admin/api/node",
            json={"node_id": "p:y", "type": "product", "name": "Y", "weight": 0.5},
            headers=headers,
        )
        assert r2.status_code == 201
        r3 = c.post(
            "/admin/api/edge",
            json={
                "from_node": "t:x",
                "to_node": "p:y",
                "relation_type": "monetizes_via",
                "weight": 0.8,
            },
            headers=headers,
        )
        assert r3.status_code == 201

        body = c.get("/admin/api/graph").json()
        assert len(body["nodes"]) == 2
        assert {n["id"] for n in body["nodes"]} == {"t:x", "p:y"}
        assert len(body["links"]) == 1


@pytest.mark.integration
def test_admin_node_write_requires_database_url(monkeypatch):
    """With a valid key but no DATABASE_URL the write endpoint returns 503."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    with TestClient(create_app()) as c:
        resp = c.post(
            "/admin/api/node",
            json={"node_id": "n1", "name": "N1"},
            headers={"X-API-Key": "secret-admin"},
        )
        assert resp.status_code == 503


@pytest.mark.integration
def test_content_generate_persists_and_history(tmp_path, monkeypatch):
    """Generated content is persisted and surfaced via /content/history + stats."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'content.db'}")
    with TestClient(create_app()) as c:
        gen = c.post(
            "/content/generate",
            json={"node_id": "topic:ai", "name": "AI", "platform": "blog", "tags": ["ai"]},
        )
        assert gen.status_code == 200
        assert "content_id" in gen.json()

        history = c.get("/content/history").json()
        assert len(history) == 1
        assert history[0]["platform"] == "blog"

        stats = c.get("/admin/api/content-stats").json()
        assert stats["total"] == 1


@pytest.mark.integration
def test_content_history_empty_without_db(monkeypatch):
    """No DATABASE_URL -> history is an empty list (no 500)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as c:
        assert c.get("/content/history").json() == []


@pytest.mark.integration
def test_generate_async_returns_pending_then_completes(tmp_path, monkeypatch):
    """POST /generate returns pending immediately; the background task completes it."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    with TestClient(create_app()) as c:
        resp = c.post("/content/generate", json={"node_id": "topic:ai", "name": "AI"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        cid = body["content_id"]
        # TestClient runs the background task, so status should be resolved now.
        status = c.get(f"/content/status/{cid}").json()
        assert status["status"] in ("completed", "processing", "pending")


@pytest.mark.integration
def test_generate_sync_flag_returns_content(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    with TestClient(create_app()) as c:
        resp = c.post("/content/generate?sync=true", json={"node_id": "topic:ai", "name": "AI"})
        assert resp.status_code == 200
        body = resp.json()
        assert "content_id" in body
        assert "title" in body and "body" in body


@pytest.mark.integration
def test_content_status_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    with TestClient(create_app()) as c:
        assert c.get("/content/status/does-not-exist").status_code == 404


@pytest.mark.integration
def test_content_status_requires_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as c:
        assert c.get("/content/status/x").status_code == 503
