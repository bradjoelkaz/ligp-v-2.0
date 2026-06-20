"""Unit tests for the SQLite asset store (database/db_store.py)."""

from __future__ import annotations

import pytest

from database import db_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the store at a throwaway DB and initialize the schema."""
    db_path = tmp_path / "trends.db"
    monkeypatch.setattr(db_store, "DB_PATH", str(db_path))
    db_store.init_db()
    return db_store


# --- raw articles ----------------------------------------------------------


def test_raw_articles_save_dedup_and_recent(store):
    articles = [
        {
            "source_id": "a1",
            "title": "T1",
            "text": "b1",
            "source_url": "u1",
            "platform": "naver",
            "published_at": "2026-01-01",
        },
        {
            "source_id": "a2",
            "title": "T2",
            "text": "b2",
            "source_url": "u2",
            "platform": "reddit",
            "published_at": "2026-01-02",
        },
    ]
    store.save_raw_articles(articles)
    store.save_raw_articles(articles)  # re-save must dedup on source_id

    recent = store.get_recent_articles(limit=10)
    assert len(recent) == 2
    assert {r["source_id"] for r in recent} == {"a1", "a2"}


def test_save_raw_articles_empty_is_noop(store):
    store.save_raw_articles([])
    assert store.get_recent_articles() == []


# --- trend topics ----------------------------------------------------------


def test_trend_topics_roundtrip(store):
    topics = [
        {
            "title": "토픽",
            "category": "IT/테크",
            "summary": "요약",
            "entities": [{"name": "OpenAI", "type": "Org"}],
            "trend_score": 0.8,
            "velocity": "+10%/24h",
            "acceleration": "상승",
            "expected_revenue": "$3.00",
            "copyright_risk": 0.1,
            "suno_prompt": "[LoFi] chill",
            "image_prompt": "cozy room",
        }
    ]
    store.save_trend_topics(topics)
    latest = store.get_latest_trends(limit=5)
    assert len(latest) == 1
    assert latest[0]["entities"] == [{"name": "OpenAI", "type": "Org"}]
    assert latest[0]["suno_prompt"] == "[LoFi] chill"


def test_save_trend_topics_empty_is_noop(store):
    store.save_trend_topics([])
    assert store.get_latest_trends() == []


# --- term volume time-series -----------------------------------------------


def test_term_volume_record_and_series(store):
    store.record_term_volumes({"AI": 5, "비트코인": 0}, ts="2026-06-19 00:00:00")
    store.record_term_volumes({"AI": 9}, ts="2026-06-20 00:00:00")
    series = store.get_term_series("AI")
    assert series == [("2026-06-19 00:00:00", 5.0), ("2026-06-20 00:00:00", 9.0)]
    # zero volume is still recorded
    assert store.get_term_series("비트코인") == [("2026-06-19 00:00:00", 0.0)]


def test_record_term_volumes_empty_is_noop(store):
    store.record_term_volumes({})
    assert store.get_term_series("anything") == []


def test_term_volume_default_timestamp(store):
    store.record_term_volumes({"X": 1})
    series = store.get_term_series("X")
    assert len(series) == 1 and series[0][1] == 1.0


# --- content feedback + totals ---------------------------------------------


def test_content_feedback_record_recent_totals(store):
    store.record_content_feedback(
        "c1",
        "blog",
        0.2,
        0.8,
        features={"w_trend": 1.0},
        metrics={"views": 1000, "clicks": 50, "subscribers": 10, "revenue": 5.0},
    )
    store.record_content_feedback("c2", "youtube", 0.3, 0.4, features={"w_revenue": 0.5})
    recent = store.get_recent_feedback()
    assert len(recent) == 2
    assert recent[-1]["features"] == {"w_trend": 1.0}  # oldest last (DESC order)

    totals = store.feedback_totals()
    assert totals["samples"] == 2
    assert totals["revenue"] == 5.0
    assert totals["subscribers"] == 10
    assert totals["views"] == 1000


def test_feedback_totals_empty(store):
    assert store.feedback_totals() == {
        "samples": 0,
        "revenue": 0.0,
        "subscribers": 0,
        "views": 0,
        "clicks": 0,
    }


# --- weights state ---------------------------------------------------------


def test_weights_save_load_upsert(store):
    assert store.load_weights() == {}
    store.save_weights({"w_trend": 0.3, "w_risk": 0.15})
    store.save_weights({"w_trend": 0.4})  # upsert
    loaded = store.load_weights()
    assert loaded["w_trend"] == 0.4
    assert loaded["w_risk"] == 0.15


def test_save_weights_empty_is_noop(store):
    store.save_weights({})
    assert store.load_weights() == {}


# --- cost ledger -----------------------------------------------------------


def test_cost_record_and_total(store):
    assert store.cost_total() == 0.0
    store.record_cost("llm", 0.01)
    store.record_cost("server", 0.02)
    assert store.cost_total() == pytest.approx(0.03)


# --- generated content -----------------------------------------------------


def test_generated_content_insert_replace_get_list(store):
    content = {
        "content_id": "yt:1",
        "format": "youtube_script",
        "platform": "youtube_shorts",
        "title": "원본",
        "body": "table",
        "segments": [{"section": "훅", "visual": "v", "narration": "n"}],
    }
    cid = store.save_generated_content(content)
    assert cid == "yt:1"
    store.save_generated_content({**content, "title": "수정됨"})  # replace

    got = store.get_generated_content("yt:1")
    assert got["title"] == "수정됨"
    assert got["segments"][0]["section"] == "훅"

    listing = store.list_generated_content()
    assert len(listing) == 1 and listing[0]["content_id"] == "yt:1"
    assert store.get_generated_content("missing") is None


def test_generated_content_derives_id_when_missing(store):
    cid = store.save_generated_content({"format": "blog", "title": "제목"})
    assert cid.startswith("blog:")
    assert store.get_generated_content(cid) is not None


# --- error paths (defensive except branches) -------------------------------


def test_all_ops_graceful_on_bad_db_path(tmp_path, monkeypatch):
    """Every op must degrade gracefully (log + default) on a broken DB path."""
    # Point at a directory path: makedirs succeeds but sqlite cannot open it.
    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path))
    db_store.init_db()  # connect fails -> caught

    # writes are no-ops (must not raise)
    db_store.save_raw_articles([{"source_id": "a", "title": "t"}])
    db_store.save_trend_topics([{"title": "t", "entities": []}])
    db_store.record_term_volumes({"x": 1})
    db_store.record_term_volumes({"x": 1}, ts="2026-01-01 00:00:00")
    db_store.record_content_feedback("c", "p", 0.1, 0.2, {"w": 1.0}, {})
    db_store.save_weights({"w": 0.1})
    db_store.record_cost("s", 0.01)
    db_store.save_generated_content({"content_id": "x", "title": "t"})

    # reads return safe defaults
    assert db_store.get_recent_articles() == []
    assert db_store.get_latest_trends() == []
    assert db_store.get_term_series("x") == []
    assert db_store.get_recent_feedback() == []
    assert db_store.feedback_totals()["samples"] == 0
    assert db_store.load_weights() == {}
    assert db_store.cost_total() == 0.0
    assert db_store.get_generated_content("x") is None
    assert db_store.list_generated_content() == []
