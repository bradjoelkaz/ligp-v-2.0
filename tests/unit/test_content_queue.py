"""Unit tests for content persistence / history / stats (Phase 10, Task #3).

Runs fully offline against SQLite via DBAdapter (no SQLAlchemy/network).
"""

from __future__ import annotations

import pytest

from api.admin import data
from database.db_adapter import DBAdapter
from database.repositories.content_repo import ContentRepository


def _repo(url: str) -> ContentRepository:
    return ContentRepository(DBAdapter(url))


def _save(repo: ContentRepository, title: str, status: str, platform: str = "blog") -> str:
    return repo.save({"title": title, "body": "b", "platform": platform, "status": status})


@pytest.mark.unit
def test_content_save_and_retrieve(tmp_path):
    repo = _repo(f"sqlite:///{tmp_path / 'c.db'}")
    cid = _save(repo, "Hello", "draft")
    got = repo.get(cid)
    assert got is not None
    assert got["title"] == "Hello"
    assert got["status"] == "draft"
    repo.db.close()


@pytest.mark.unit
def test_content_list_filters_and_limit(tmp_path):
    repo = _repo(f"sqlite:///{tmp_path / 'c.db'}")
    _save(repo, "A", "draft")
    _save(repo, "B", "published")
    _save(repo, "C", "published")

    published = repo.list_content(status="published")
    assert {r["title"] for r in published} == {"B", "C"}
    assert all(r["status"] == "published" for r in published)

    limited = repo.list_content(limit=1)
    assert len(limited) == 1
    # listed rows expose the summary columns only
    assert set(limited[0]) == {
        "content_id",
        "title",
        "status",
        "platform",
        "created_at",
        "updated_at",
    }
    repo.db.close()


@pytest.mark.unit
def test_content_list_since_filter(tmp_path):
    repo = _repo(f"sqlite:///{tmp_path / 'c.db'}")
    _save(repo, "A", "draft")
    assert len(repo.list_content(since="2000-01-01T00:00:00")) == 1
    assert repo.list_content(since="2099-01-01T00:00:00") == []
    repo.db.close()


@pytest.mark.unit
def test_content_counts(tmp_path):
    repo = _repo(f"sqlite:///{tmp_path / 'c.db'}")
    _save(repo, "A", "draft")
    _save(repo, "B", "published")
    _save(repo, "C", "published")
    counts = repo.counts()
    assert counts["total"] == 3
    assert counts["by_status"] == {"draft": 1, "published": 2}
    repo.db.close()


@pytest.mark.unit
def test_content_stats_from_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    repo = _repo(url)
    _save(repo, "A", "published")
    _save(repo, "B", "failed")
    repo.db.close()

    monkeypatch.setenv("DATABASE_URL", url)
    stats = data.content_stats()
    assert stats["total"] == 2
    assert stats["by_status"] == {"failed": 1, "published": 1}


@pytest.mark.unit
def test_content_stats_seed_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    stats = data.content_stats()
    # Seed fallback derives from the representative queue (non-empty).
    assert stats["total"] >= 1
    assert isinstance(stats["by_status"], dict)
