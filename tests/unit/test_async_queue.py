"""Unit tests for the async content queue (Phase 11).

Exercise the module-level helpers and the ``_process_content`` background worker
directly (no FastAPI needed) against offline SQLite. The generator/quality gate
are monkeypatched so the DB state transitions are what we assert.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from api.routes import content as content_mod
from database.db_adapter import DBAdapter
from database.repositories.content_repo import ContentRepository


def _repo(url: str) -> ContentRepository:
    return ContentRepository(DBAdapter(url))


def _stub_generation(monkeypatch, *, fail: bool = False) -> None:
    from content_factory import quality_gate
    from content_factory.generators import blog_generator

    async def _fake_gen(self, node, platform, template=None):
        if fail:
            raise RuntimeError("gen down")
        return {"title": "T", "body": "B", "platform": platform, "tags": node.get("tags", [])}

    monkeypatch.setattr(blog_generator.BlogGenerator, "generate_async", _fake_gen)
    monkeypatch.setattr(quality_gate.QualityGate, "check", lambda self, c, p: (True, []))


@pytest.mark.unit
def test_persist_pending_writes_row(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid1", "[pending] X", "blog")
    repo = _repo(url)
    try:
        row = repo.get("cid1")
        assert row is not None
        assert row["status"] == "pending"
        assert row["platform"] == "blog"
    finally:
        repo.db.close()


@pytest.mark.unit
def test_persist_pending_noop_without_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Must not raise even though there is no DB.
    content_mod._persist_pending("x", "t", "blog")


@pytest.mark.unit
def test_process_content_success(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch)

    asyncio.run(content_mod._process_content("cid", "n", "Name", "blog", ["t"]))

    repo = _repo(url)
    try:
        row = repo.get("cid")
        assert row["status"] == "completed"
        payload = json.loads(row["payload"])
        assert payload["title"] == "T"
        assert payload["quality_passed"] is True
    finally:
        repo.db.close()


@pytest.mark.unit
def test_process_content_failure_is_recorded_not_raised(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch, fail=True)

    # Must NOT raise (background worker safety).
    asyncio.run(content_mod._process_content("cid", "n", "Name", "blog", []))

    repo = _repo(url)
    try:
        row = repo.get("cid")
        assert row["status"] == "failed"
        assert "error" in json.loads(row["payload"])
    finally:
        repo.db.close()


@pytest.mark.unit
def test_update_status_stores_result(tmp_path):
    repo = _repo(f"sqlite:///{tmp_path / 'c.db'}")
    try:
        repo.save({"content_id": "c1", "title": "T", "platform": "blog", "status": "pending"})
        repo.update_status("c1", "completed", result='{"k": 1}')
        row = repo.get("c1")
        assert row["status"] == "completed"
        assert json.loads(row["payload"]) == {"k": 1}
    finally:
        repo.db.close()


@pytest.mark.unit
def test_update_status_preserves_payload_when_no_result(tmp_path):
    repo = _repo(f"sqlite:///{tmp_path / 'c.db'}")
    try:
        repo.save({"content_id": "c1", "title": "T", "platform": "blog", "status": "draft"})
        original = repo.get("c1")["payload"]
        repo.update_status("c1", "published")  # legacy 2-arg call
        row = repo.get("c1")
        assert row["status"] == "published"
        assert row["payload"] == original  # unchanged
    finally:
        repo.db.close()


@pytest.mark.unit
def test_list_history_helper(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("c1", "A", "blog")
    content_mod._persist_pending("c2", "B", "youtube")
    rows = content_mod._list_history(limit=10)
    assert len(rows) == 2


@pytest.mark.unit
def test_list_history_empty_without_db(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert content_mod._list_history() == []
