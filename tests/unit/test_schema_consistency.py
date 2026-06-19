"""Schema-consistency tests (Phase 10/15).

Guards the raw-SQL repositories against drifting from the unified schema. The
repository columns are read from a real SQLite table (PRAGMA) and compared to
the canonical unified column sets. The migration (``003``) is now ALTER-based
and validated end-to-end against PostgreSQL by
``tests/integration/test_postgres_compatibility.py`` (alembic upgrade head +
repo CRUD on the same tables), so we no longer parse the migration text here.
"""

from __future__ import annotations

import pytest

from database.db_adapter import DBAdapter
from database.repositories.content_repo import ContentRepository
from database.repositories.node_repo import NodeRepository

# Canonical unified column sets (kept in lock-step with node_repo/content_repo
# _SCHEMA and the Alembic 003 result).
NODE_COLUMNS = {
    "node_id",
    "type",
    "name",
    "weight",
    "embedding",
    "lang",
    "graph_score",
    "revenue_score",
    "trend_state",
    "created_at",
    "updated_at",
}
CONTENT_COLUMNS = {
    "content_id",
    "node_id",
    "platform",
    "status",
    "title",
    "body",
    "payload",
    "tags",
    "quality_score",
    "published_url",
    "published_at",
    "generator",
    "llm_cost_usd",
    "created_at",
    "updated_at",
}


def _table_columns(repo_cls, table: str) -> set[str]:
    db = DBAdapter("sqlite:///:memory:")
    db.connect()
    try:
        repo_cls(db)  # __init__ creates the table
        return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


@pytest.mark.unit
def test_nodes_repo_has_unified_columns():
    assert _table_columns(NodeRepository, "nodes") == NODE_COLUMNS


@pytest.mark.unit
def test_content_repo_has_unified_columns():
    assert _table_columns(ContentRepository, "content") == CONTENT_COLUMNS


@pytest.mark.unit
def test_nodes_old_001_columns_are_gone():
    cols = _table_columns(NodeRepository, "nodes")
    assert "label" not in cols  # renamed -> name
    assert "embedding_path" not in cols  # renamed -> embedding


@pytest.mark.unit
def test_node_repo_crud_on_unified_schema(tmp_path):
    db = DBAdapter(f"sqlite:///{tmp_path / 'n.db'}")
    db.connect()
    try:
        repo = NodeRepository(db)
        repo.upsert({"node_id": "n1", "type": "topic", "name": "A", "weight": 1.5})
        repo.upsert({"node_id": "n1", "type": "topic", "name": "A2", "weight": 2.0})  # idempotent
        got = repo.get("n1")
        assert got["name"] == "A2"
        assert got["lang"] == "ko"
        assert got["trend_state"] == "unknown"
    finally:
        db.close()


@pytest.mark.unit
def test_edges_table_not_created_by_repos():
    db = DBAdapter("sqlite:///:memory:")
    db.connect()
    try:
        NodeRepository(db)
        ContentRepository(db)
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges'")
        assert rows == []
    finally:
        db.close()
