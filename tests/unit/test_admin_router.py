"""Unit tests for the admin dashboard.

The :mod:`api.admin.data` layer is framework-free and tested directly. The
route tests build the real FastAPI app and use ``TestClient``; they are gated
behind ``importorskip`` for ``fastapi``/``httpx`` so they skip cleanly when the
web stack is not installed (CI installs requirements-dev and runs them).
"""

from __future__ import annotations

import pytest

from api.admin import data


# --------------------------------------------------------------------------
# Data layer (no web dependencies required)
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_load_seed_graph_has_nodes_and_edges():
    graph = data.load_seed_graph()
    assert len(graph["nodes"]) == 12
    assert len(graph["edges"]) == 12


@pytest.mark.unit
def test_graph_payload_shape_and_colors():
    payload = data.graph_payload()
    assert set(payload) == {"nodes", "links"}
    assert len(payload["nodes"]) == 12
    assert len(payload["links"]) == 12
    first = payload["nodes"][0]
    assert {"id", "name", "type", "weight", "color"} <= set(first)
    # Every node colour is a hex string from the type palette.
    assert all(n["color"].startswith("#") for n in payload["nodes"])
    # Links reference source/target ids.
    assert all({"source", "target", "relation", "weight"} <= set(link) for link in payload["links"])


@pytest.mark.unit
def test_graph_stats_counts_and_breakdowns():
    stats = data.graph_stats()
    assert stats["node_count"] == 12
    assert stats["edge_count"] == 12
    assert stats["nodes_by_type"]["topic"] == 4
    assert stats["edges_by_relation"]["monetizes_via"] == 3


@pytest.mark.unit
def test_top_revenue_paths_are_monetizing_and_sorted():
    paths = data.top_revenue_paths(limit=5)
    assert len(paths) == 3  # three monetizes_via edges in the seed graph
    weights = [p["weight"] for p in paths]
    assert weights == sorted(weights, reverse=True)
    assert all(p["weight"] == 0.9 for p in paths)


@pytest.mark.unit
def test_content_queue_schema():
    items = data.content_queue()
    assert items, "content queue should not be empty"
    for item in items:
        assert {"id", "title", "channel", "status", "quality_score"} <= set(item)
        assert 0.0 <= item["quality_score"] <= 1.0


@pytest.mark.unit
def test_experiment_summary_schema():
    experiments = data.experiment_summary()
    assert len(experiments) == 2
    for exp in experiments:
        assert {"experiment_id", "variant_a", "variant_b", "status"} <= set(exp)


@pytest.mark.unit
def test_dashboard_summary_is_resilient_without_config():
    # _safe_config returns {} when PyYAML is unavailable; summary must still work.
    summary = data.dashboard_summary()
    assert summary["node_count"] == 12
    assert summary["edge_count"] == 12
    assert "app_version" in summary
    assert summary["phase"].startswith("Phase 8")


@pytest.mark.unit
def test_settings_view_returns_dict():
    view = data.settings_view()
    assert isinstance(view, dict)


# --------------------------------------------------------------------------
# Route layer (requires FastAPI + httpx)
# --------------------------------------------------------------------------
@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("jinja2")
    from fastapi.testclient import TestClient

    from api.main import create_app

    # Context-manager form triggers the lifespan (metrics init) on enter/exit.
    with TestClient(create_app()) as c:
        yield c


@pytest.mark.unit
def test_system_endpoints(client):
    assert client.get("/health").json()["status"] == "healthy"
    assert client.get("/ready").status_code == 200
    assert client.get("/version").status_code == 200
    assert client.get("/").json()["service"] == "iigp"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]


@pytest.mark.unit
def test_admin_index_renders_html(client):
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Overview" in resp.text


@pytest.mark.unit
@pytest.mark.parametrize(
    "path", ["/admin/graph", "/admin/content", "/admin/experiments", "/admin/settings"]
)
def test_admin_pages_render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.unit
def test_admin_api_graph_returns_json(client):
    resp = client.get("/admin/api/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 12
    assert len(body["links"]) == 12


@pytest.mark.unit
def test_admin_api_stats_returns_json(client):
    resp = client.get("/admin/api/stats")
    assert resp.status_code == 200
    assert resp.json()["node_count"] == 12
