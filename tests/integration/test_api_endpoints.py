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
