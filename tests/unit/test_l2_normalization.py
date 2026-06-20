"""Tests for L2 normalization helpers (ingestion/collectors/feeds.py)."""

from __future__ import annotations

from ingestion.collectors.feeds import detect_language, enrich_l2


def test_detect_language_korean():
    assert detect_language("안녕하세요 AI 뉴스") == "ko"


def test_detect_language_english():
    assert detect_language("Hello AI news") == "en"


def test_detect_language_empty_defaults_en():
    assert detect_language("") == "en"


def test_enrich_l2_sets_language_country_engagement():
    doc = {"title": "삼성 갤럭시", "text": "신제품", "platform": "naver"}
    enrich_l2(doc)
    assert doc["language"] == "ko"
    assert doc["country"] == "KR"
    assert doc["engagement"] == {"views": 0, "likes": 0, "comments": 0, "shares": 0}


def test_enrich_l2_normalizes_partial_engagement():
    doc = {
        "title": "x",
        "text": "y",
        "platform": "reddit",
        "engagement": {"likes": 42, "comments": 7},
    }
    enrich_l2(doc)
    assert doc["country"] == "US"
    assert doc["engagement"] == {"views": 0, "likes": 42, "comments": 7, "shares": 0}


def test_enrich_l2_preserves_explicit_values():
    doc = {"title": "x", "platform": "youtube", "language": "ja", "country": "JP"}
    enrich_l2(doc)
    assert doc["language"] == "ja"
    assert doc["country"] == "JP"


def test_enrich_l2_unknown_platform_blank_country():
    doc = {"title": "Hello", "platform": "weird"}
    enrich_l2(doc)
    assert doc["country"] == ""
    assert doc["language"] == "en"
