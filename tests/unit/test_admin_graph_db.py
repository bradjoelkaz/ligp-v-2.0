"""Unit tests for the DB-aware admin graph source (Phase 9).

Verifies api.admin.data uses the persisted graph (graph_nodes/graph_edges) when
DATABASE_URL is set and populated, and falls back to the seed graph otherwise.
Uses a temporary file-based SQLite DB so a fresh DBAdapter sees the data.
"""

from __future__ import annotations

import pytest

from api.admin import data
from database.db_adapter import DBAdapter
from database.repositories.graph_repo import GraphRepository


def _seed_db(url: str) -> None:
    repo = GraphRepository(DBAdapter(url))
    repo.upsert_node("topic:db", "topic", "DB Topic", 1.0)
    repo.upsert_node("product:x", "product", "Product X", 0.7)
    repo.upsert_edge("topic:db", "product:x", "monetizes_via", 0.95)
    repo.db.close()


@pytest.mark.unit
def test_falls_back_to_seed_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert data._db_graph() is None
    # graph_stats reflects the 12-node seed graph.
    assert data.graph_stats()["node_count"] == 12


@pytest.mark.unit
def test_uses_database_when_populated(tmp_path, monkeypatch):
    db_file = tmp_path / "graph.db"
    url = f"sqlite:///{db_file}"
    _seed_db(url)
    monkeypatch.setenv("DATABASE_URL", url)

    db_graph = data._db_graph()
    assert db_graph is not None
    assert len(db_graph["nodes"]) == 2

    # graph_payload / graph_stats now reflect the DB, not the seed.
    payload = data.graph_payload()
    assert len(payload["nodes"]) == 2
    assert {n["id"] for n in payload["nodes"]} == {"topic:db", "product:x"}

    stats = data.graph_stats()
    assert stats["node_count"] == 2
    assert stats["edge_count"] == 1

    # The monetizes_via edge is surfaced as a revenue path.
    paths = data.top_revenue_paths()
    assert paths and paths[0]["weight"] == 0.95


@pytest.mark.unit
def test_falls_back_to_seed_when_db_empty(tmp_path, monkeypatch):
    db_file = tmp_path / "empty.db"
    url = f"sqlite:///{db_file}"
    GraphRepository(DBAdapter(url)).db.close()  # create empty tables
    monkeypatch.setenv("DATABASE_URL", url)

    # Empty DB -> _db_graph returns None -> seed graph (12 nodes) is used.
    assert data._db_graph() is None
    assert data.graph_stats()["node_count"] == 12


@pytest.mark.unit
def test_db_error_falls_back_to_seed(monkeypatch):
    # A postgres URL with psycopg unavailable must be swallowed -> seed.
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5/none")
    assert data._db_graph() is None
    assert data.graph_stats()["node_count"] == 12
