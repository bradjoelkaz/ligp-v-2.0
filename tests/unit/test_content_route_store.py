"""Tests for content-route SQLite persistence helper (api/routes/content.py)."""

from __future__ import annotations

from api.routes import content as content_route
from database import db_store


def test_save_generated_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path / "c.db"))
    content = {
        "content_id": "abc",
        "format": "youtube_script",
        "platform": "youtube_shorts",
        "title": "제목",
        "body": "table",
        "quality_passed": True,
        "llm_critique": {"score": 90},
    }
    content_route._save_generated(content)

    got = db_store.get_generated_content("abc")
    assert got is not None
    assert got["title"] == "제목"
    assert got["llm_critique"]["score"] == 90


def test_save_generated_graceful_on_bad_path(tmp_path, monkeypatch):
    # Point DB at a directory so sqlite cannot open it -> must not raise.
    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path))
    content_route._save_generated({"content_id": "x", "title": "t", "body": "b"})
    # nothing persisted, but call returned cleanly
    assert db_store.get_generated_content("x") is None
