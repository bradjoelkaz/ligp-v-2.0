"""Unit tests for GraphRepository (Phase 9).

Runs fully offline against an in-memory SQLite database (stdlib sqlite3 via
DBAdapter) — no SQLAlchemy/psycopg/Postgres required.
"""

from __future__ import annotations

import pytest

from database.db_adapter import DBAdapter
from database.repositories.graph_repo import GraphRepository


@pytest.fixture
def repo() -> GraphRepository:
    # A single in-memory DBAdapter keeps one connection alive for the test.
    return GraphRepository(DBAdapter("sqlite:///:memory:"))


@pytest.mark.unit
def test_empty_repo_counts_and_graph(repo: GraphRepository):
    assert repo.counts() == (0, 0)
    assert repo.as_graph() == {"nodes": [], "edges": []}


@pytest.mark.unit
def test_upsert_node_and_fetch(repo: GraphRepository):
    repo.upsert_node("topic:ai", "topic", "AI", 1.0)
    repo.upsert_node("product:course", "product", "Course", 0.8)
    nodes = repo.fetch_nodes()
    assert len(nodes) == 2
    assert {n["id"] for n in nodes} == {"topic:ai", "product:course"}
    assert set(nodes[0]) == {"id", "type", "name", "weight"}


@pytest.mark.unit
def test_upsert_node_is_idempotent_update(repo: GraphRepository):
    repo.upsert_node("topic:ai", "topic", "AI", 1.0)
    repo.upsert_node("topic:ai", "topic", "AI v2", 0.5)
    assert repo.counts()[0] == 1
    node = repo.get_node("topic:ai")
    assert node is not None
    assert node["name"] == "AI v2"
    assert node["weight"] == 0.5


@pytest.mark.unit
def test_upsert_edge_and_fetch(repo: GraphRepository):
    repo.upsert_node("topic:ai", "topic", "AI", 1.0)
    repo.upsert_node("product:course", "product", "Course", 0.8)
    edge_id = repo.upsert_edge("topic:ai", "product:course", "monetizes_via", 0.9)
    assert edge_id == "topic:ai->product:course:monetizes_via"
    edges = repo.fetch_edges()
    assert len(edges) == 1
    assert edges[0] == {
        "from_node": "topic:ai",
        "to_node": "product:course",
        "relation_type": "monetizes_via",
        "weight": 0.9,
    }


@pytest.mark.unit
def test_upsert_edge_is_idempotent_on_weight(repo: GraphRepository):
    repo.upsert_node("a", "topic", "A", 1.0)
    repo.upsert_node("b", "topic", "B", 1.0)
    repo.upsert_edge("a", "b", "related_to", 0.3)
    repo.upsert_edge("a", "b", "related_to", 0.7)
    assert repo.counts() == (2, 1)
    assert repo.fetch_edges()[0]["weight"] == 0.7


@pytest.mark.unit
def test_get_node_missing_returns_none(repo: GraphRepository):
    assert repo.get_node("nope") is None
