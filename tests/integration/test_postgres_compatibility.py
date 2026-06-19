"""PostgreSQL compatibility integration test (Phase 15).

Runs ONLY when ``TEST_POSTGRES_URL`` is set (CI provides a postgres service);
otherwise the module is skipped, so local/offline workflows are unaffected.

It runs the Alembic migrations against PostgreSQL and exercises the raw-SQL
repositories (which use psycopg3 via DBAdapter) to prove the schema + queries
are dialect-compatible.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("psycopg")  # psycopg3 — DBAdapter driver
pytest.importorskip("alembic")
pytest.importorskip("sqlalchemy")

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_POSTGRES_URL, reason="TEST_POSTGRES_URL not set"),
]

from database.db_adapter import DBAdapter  # noqa: E402
from database.repositories.content_repo import ContentRepository  # noqa: E402
from database.repositories.node_repo import NodeRepository  # noqa: E402


@pytest.fixture(scope="module")
def pg_url():
    """Migrate a fresh postgres schema (alembic upgrade head), then tear down.

    Alembic/SQLAlchemy use the psycopg3 dialect (``postgresql+psycopg://``); the
    repositories connect with the plain ``postgresql://`` URL (psycopg3 libpq).
    """
    from alembic import command
    from alembic.config import Config

    sa_url = TEST_POSTGRES_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sa_url  # env.py reads this
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    try:
        yield TEST_POSTGRES_URL
    finally:
        try:
            command.downgrade(cfg, "base")
        finally:
            if prev is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = prev


@pytest.mark.integration
def test_migrations_create_expected_tables(pg_url):
    db = DBAdapter(pg_url)
    db.connect()
    try:
        rows = db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        names = {r["table_name"] for r in rows}
        assert {"nodes", "content", "graph_nodes", "graph_edges"} <= names
    finally:
        db.close()


@pytest.mark.integration
def test_node_repository_crud_on_postgres(pg_url):
    db = DBAdapter(pg_url)
    try:
        repo = NodeRepository(db)
        repo.upsert(
            {"node_id": "pg1", "type": "topic", "name": "A", "weight": 1.0, "embedding": [1.0, 0.0]}
        )
        # ON CONFLICT ... DO UPDATE must work on postgres.
        repo.upsert(
            {
                "node_id": "pg1",
                "type": "topic",
                "name": "A2",
                "weight": 2.0,
                "embedding": [1.0, 0.0],
            }
        )
        got = repo.get("pg1")
        assert got is not None and got["name"] == "A2"
        results = repo.search_by_embedding([1.0, 0.0], top_k=1)
        assert results[0]["node_id"] == "pg1"
    finally:
        db.close()


@pytest.mark.integration
def test_content_repository_crud_on_postgres(pg_url):
    db = DBAdapter(pg_url)
    try:
        repo = ContentRepository(db)
        cid = repo.save({"title": "T", "body": "B", "platform": "blog", "status": "draft"})
        assert repo.get(cid)["title"] == "T"
        repo.update_status(cid, "published")
        assert repo.get(cid)["status"] == "published"
        assert len(repo.list_content(status="published")) == 1
        assert repo.counts()["total"] >= 1
    finally:
        db.close()
