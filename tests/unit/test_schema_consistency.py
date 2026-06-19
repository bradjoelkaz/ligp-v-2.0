"""Schema-consistency tests (Phase 10 cleanup).

Guards against the raw-SQL repositories drifting from the Alembic ``003``
migration again. The repository columns are read from the actual SQLite table
(PRAGMA); the migration columns are parsed from the ``003`` file *as text* so no
SQLAlchemy import is required (it runs offline).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from database.db_adapter import DBAdapter
from database.repositories.content_repo import ContentRepository
from database.repositories.node_repo import NodeRepository

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "003_unify_schemas.py"
)


def _migration_columns(builder_fn: str) -> set[str]:
    """Column names from a create-table builder function in the 003 migration."""
    text = _MIGRATION.read_text(encoding="utf-8")
    start = text.index(f"def {builder_fn}")
    rest = text[start:]
    end = rest.find("\ndef ", 1)
    block = rest if end == -1 else rest[:end]
    return set(re.findall(r'sa\.Column\(\s*"(\w+)"', block))


def _table_columns(repo_cls, table: str) -> set[str]:
    db = DBAdapter("sqlite:///:memory:")
    db.connect()
    try:
        repo_cls(db)  # __init__ creates the table
        return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


@pytest.mark.unit
def test_nodes_repo_matches_migration():
    assert _table_columns(NodeRepository, "nodes") == _migration_columns("_create_unified_nodes")


@pytest.mark.unit
def test_content_repo_matches_migration():
    assert _table_columns(ContentRepository, "content") == _migration_columns(
        "_create_unified_content"
    )


@pytest.mark.unit
def test_nodes_unified_columns_present():
    cols = _table_columns(NodeRepository, "nodes")
    assert {"name", "weight", "embedding", "lang", "graph_score", "trend_state"} <= cols
    assert "label" not in cols  # old 001 column name is gone
    assert "embedding_path" not in cols


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
        # New unified columns exist with defaults.
        assert got["lang"] == "ko"
        assert got["trend_state"] == "unknown"
    finally:
        db.close()


@pytest.mark.unit
def test_edges_table_not_created_by_repos():
    # The dead 001 'edges' table must not be resurrected by any raw-SQL repo.
    db = DBAdapter("sqlite:///:memory:")
    db.connect()
    try:
        NodeRepository(db)
        ContentRepository(db)
        rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges'")
        assert rows == []
    finally:
        db.close()
