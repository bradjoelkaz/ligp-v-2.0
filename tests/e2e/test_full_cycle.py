"""End-to-end Phases 1-7 data cycle (Phase 8 verification).

Drives the real production layer functions \u2014 collect/L2 normalize, persist,
analyze, time-series, virtual deploy, performance feedback, weight calibration,
and the OS dashboard contract \u2014 against a temporary SQLite asset store. No
network or web stack required, so it runs offline and in CI (Job 4).
"""

from __future__ import annotations

import sqlite3

import pytest

import database.db_store as db_store
from api.admin import data as admin_data
from feedback_engine import performance_collector as pc
from ingestion.collectors.feeds import enrich_l2
from nlp.llm_processor import GeminiProcessor
from publisher import deploy_engine as de
from time_engine import volume_tracker as vt

_RAW_DOCS = [
    {
        "source_id": "yt_v1",
        "title": "AI \uc2e0\ubaa8\ub378 \uacf5\uac1c",
        "text": "\ud55c\uad6d\uc5b4 AI \ud2b8\ub80c\ub4dc \uc601\uc0c1",
        "source_url": "https://youtube.com/watch?v=v1",
        "platform": "youtube",
        "published_at": "2026-06-20",
        "engagement": {"views": 10000, "likes": 800, "comments": 120},
    },
    {
        "source_id": "rd_r1",
        "title": "AI breakthrough",
        "text": "english discussion about chips",
        "source_url": "https://reddit.com/r/tech/r1",
        "platform": "reddit",
        "published_at": "2026-06-20",
        "engagement": {"likes": 1234, "comments": 56},
    },
]


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path / "e2e_cycle.db"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    db_store.init_db()
    return db_store


@pytest.mark.e2e
def test_full_cycle_persists_all_tables(store):
    # 1. L2 normalization (language / country / engagement).
    docs = [enrich_l2(dict(d)) for d in _RAW_DOCS]
    yt = next(d for d in docs if d["platform"] == "youtube")
    rd = next(d for d in docs if d["platform"] == "reddit")
    assert yt["language"] == "ko" and yt["country"] == ""
    assert rd["language"] == "en" and rd["country"] == "US"
    assert rd["engagement"]["likes"] == 1234

    # 2. Persist raw_articles with L2 columns.
    store.save_raw_articles(docs)
    recent = store.get_recent_articles()
    assert any(r["likes"] == 1234 for r in recent)
    assert {r["language"] for r in recent} == {"ko", "en"}

    # 3. Analyze (mock LLM) + persist topics with Suno/image prompts.
    topics = GeminiProcessor().analyze_trends(docs).get("topics", [])
    assert topics and all("suno_prompt" in t and "image_prompt" in t for t in topics)
    store.save_trend_topics(topics)
    assert store.get_latest_trends()

    # 4. Layer-4 volume snapshot.
    vt.record_snapshot(docs, [t["title"] for t in topics], store=store)

    # 5. Virtual deploy (mock) across platforms.
    for i, t in enumerate(topics):
        platform = ("tistory", "youtube", "wordpress")[i % 3]
        res = de.deploy({"content_id": f"topic{i}", "title": t["title"]}, platform, store=store)
        assert res["status"] == "mock"
    assert len(store.get_deployments()) == len(topics)
    assert store.deployment_mix()

    # 6. Performance feedback + L7 calibration (weights_history snapshot).
    items = [
        {
            "content_id": f"topic{i}",
            "platform": "blog",
            "expected_score": 0.2,
            "features": {"w_trend": 1.0, "w_revenue": 0.5, "w_risk": 0.1},
        }
        for i in range(len(topics))
    ]
    summary = pc.collect_and_calibrate(items, store=store)
    assert summary["samples"] == len(topics)
    assert store.feedback_totals()["samples"] == len(topics)
    assert store.get_weights_history()

    # 7. OS dashboard data contract (what /admin/os renders).
    osd = admin_data.os_dashboard()
    for key in (
        "mission",
        "finance",
        "portfolio",
        "deployments",
        "deploy_mix",
        "weights_history",
        "current_weights",
        "feedback_samples",
    ):
        assert key in osd, f"os_dashboard missing {key}"
    assert osd["deploy_mix"] and osd["current_weights"]
    assert osd["feedback_samples"] == len(topics)

    # All nine asset tables exist and the populated ones have rows.
    con = sqlite3.connect(db_store.DB_PATH)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in (
            "raw_articles",
            "trend_topics",
            "term_volume",
            "content_feedback",
            "deployments",
            "weights_history",
            "weights_state",
        ):
            assert t in tables, f"missing table {t}"
            assert con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] > 0, f"{t} empty"
    finally:
        con.close()
