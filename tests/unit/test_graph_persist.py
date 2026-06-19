"""Unit tests for the pipeline -> DB graph persistence hook (Phase 9).

Runs offline against SQLite. Verifies no-op without DATABASE_URL, successful
upsert, error swallowing (worker safety), empty store, and idempotency.
"""

from __future__ import annotations

import pytest

from database.db_adapter import DBAdapter
from database.repositories.graph_repo import GraphRepository
from graph.graph_store import Edge, InMemoryGraphStore, Node
from orchestration.hooks.graph_persist import persist_graph_to_db


def _store_with_data() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.add_node(Node(id="topic:ai", type="topic", name="AI", weight=1.0))
    store.add_node(Node(id="product:course", type="product", name="Course", weight=0.8))
    store.add_edge(Edge("topic:ai", "product:course", "monetizes_via", 0.9))
    return store


@pytest.mark.unit
def test_persist_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert persist_graph_to_db(_store_with_data()) is False


@pytest.mark.unit
def test_persist_success_sqlite(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'persist.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    assert persist_graph_to_db(_store_with_data()) is True

    # Verify the rows landed in the DB.
    repo = GraphRepository(DBAdapter(url))
    try:
        assert repo.counts() == (2, 1)
        assert {n["id"] for n in repo.fetch_nodes()} == {"topic:ai", "product:course"}
        assert repo.fetch_edges()[0]["relation_type"] == "monetizes_via"
    finally:
        repo.db.close()


@pytest.mark.unit
def test_persist_empty_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    assert persist_graph_to_db(InMemoryGraphStore()) is True


@pytest.mark.unit
def test_persist_idempotent(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'idem.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    store = _store_with_data()
    assert persist_graph_to_db(store) is True
    assert persist_graph_to_db(store) is True  # second call: no duplicates

    repo = GraphRepository(DBAdapter(url))
    try:
        assert repo.counts() == (2, 1)
    finally:
        repo.db.close()


@pytest.mark.unit
def test_persist_db_error_is_swallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'boom.db'}")

    class _BoomRepo:
        def __init__(self, *a, **k):
            raise RuntimeError("db down")

    # GraphRepository is imported lazily inside the hook, so patch its source.
    import database.repositories.graph_repo as gr

    monkeypatch.setattr(gr, "GraphRepository", _BoomRepo)
    assert persist_graph_to_db(_store_with_data()) is False
