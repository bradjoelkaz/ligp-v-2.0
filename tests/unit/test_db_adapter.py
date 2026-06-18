"""Tests for DBAdapter and repositories (Layer 13)."""

from __future__ import annotations

import pytest

from database.db_adapter import DBAdapter
from database.repositories.content_repo import ContentRepository
from database.repositories.node_repo import NodeRepository


@pytest.fixture()
def db():
    d = DBAdapter("sqlite:///:memory:")
    d.connect()
    yield d
    d.close()


@pytest.mark.unit
def test_execute_create_insert_select(db):
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO t (id, name) VALUES (?, ?)", (1, "alpha"))
    rows = db.execute("SELECT * FROM t")
    assert rows == [{"id": 1, "name": "alpha"}]


@pytest.mark.unit
def test_executemany(db):
    db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    db.executemany("INSERT INTO t (id, name) VALUES (?, ?)", [(1, "a"), (2, "b"), (3, "c")])
    rows = db.execute("SELECT COUNT(*) AS n FROM t")
    assert rows[0]["n"] == 3


@pytest.mark.unit
def test_transaction_rollback(db):
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute("INSERT INTO t (id) VALUES (1)")
            raise RuntimeError("boom")
    rows = db.execute("SELECT COUNT(*) AS n FROM t")
    assert rows[0]["n"] == 0


@pytest.mark.unit
def test_backend_detection():
    assert DBAdapter("sqlite:///:memory:").backend == "sqlite"
    assert DBAdapter("postgresql://localhost/db").backend == "postgres"


@pytest.mark.unit
def test_content_repository_crud(db):
    repo = ContentRepository(db)
    cid = repo.save({"title": "T", "body": "B", "platform": "blog", "status": "draft"})
    got = repo.get(cid)
    assert got is not None and got["title"] == "T"
    repo.update_status(cid, "published")
    assert repo.get(cid)["status"] == "published"
    assert len(repo.list_by_status("published")) == 1
    assert repo.list_by_status("draft") == []


@pytest.mark.unit
def test_content_repository_missing(db):
    repo = ContentRepository(db)
    assert repo.get("missing") is None


@pytest.mark.unit
def test_node_repository_upsert_and_search(db):
    repo = NodeRepository(db)
    repo.upsert(
        {"node_id": "n1", "type": "topic", "name": "A", "weight": 1.0, "embedding": [1.0, 0.0, 0.0]}
    )
    repo.upsert(
        {"node_id": "n2", "type": "topic", "name": "B", "weight": 1.0, "embedding": [0.0, 1.0, 0.0]}
    )
    # upsert updates rather than duplicates
    repo.upsert(
        {
            "node_id": "n1",
            "type": "topic",
            "name": "A2",
            "weight": 2.0,
            "embedding": [1.0, 0.0, 0.0],
        }
    )
    assert repo.get("n1")["name"] == "A2"
    results = repo.search_by_embedding([1.0, 0.0, 0.0], top_k=1)
    assert results[0]["node_id"] == "n1"


@pytest.mark.unit
def test_node_repository_search_skips_missing_embeddings(db):
    repo = NodeRepository(db)
    repo.upsert({"node_id": "n1", "type": "topic", "name": "A", "weight": 1.0})
    assert repo.search_by_embedding([1.0, 0.0], top_k=5) == []
