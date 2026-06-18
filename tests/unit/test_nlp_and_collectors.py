"""Tests for language detection, NER fallback routing, and collector parsing."""

from __future__ import annotations

import pytest

from ingestion.reddit.collector import RedditCollector
from ingestion.rss.collector import RSSCollector
from ingestion.youtube.collector import YouTubeCollector
from nlp.entity_extractor import EntityExtractor, WikiDataLinker
from processing.language_detector import detect_language


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello world, this is an English sentence.", "en"),
        ("안녕하세요 오늘 날씨가 좋네요", "ko"),
        ("これはにほんごのテストです", "ja"),
        ("这是一个中文句子测试", "zh"),
    ],
)
def test_language_detector_heuristic(text, expected):
    # Heuristic fallback is exercised when langdetect/fasttext are absent.
    assert detect_language(text) == expected


@pytest.mark.unit
def test_language_detector_empty_is_other():
    assert detect_language("") == "other"


@pytest.mark.unit
def test_entity_extractor_fallback_finds_capitalized_entities():
    ex = EntityExtractor()
    ents = ex.extract("OpenAI and NVIDIA announced a partnership in California")
    surfaces = {e.text for e in ents}
    assert any("OpenAI" in s for s in surfaces)
    assert any("NVIDIA" in s for s in surfaces)


@pytest.mark.unit
def test_entity_extractor_confidence_gate():
    ex = EntityExtractor(confidence_min=0.99)
    # fallback emits 0.90 confidence -> gated out at 0.99
    assert ex.extract("OpenAI announced something") == []


@pytest.mark.unit
def test_wikidata_linker_merges_aliases():
    linker = WikiDataLinker({"openai": "Q1", "open ai": "Q1"})
    from nlp.entity_extractor import Entity

    ents = [Entity("OpenAI", "ORG", 0.9), Entity("Open AI", "ORG", 0.95)]
    merged = linker.link_all(ents)
    assert len(merged) == 1
    assert merged[0].qid == "Q1"
    assert merged[0].confidence == 0.95  # keeps highest-confidence mention


@pytest.mark.unit
def test_rss_collector_parses_rss2():
    xml = """<?xml version='1.0'?>
    <rss version='2.0'><channel>
      <item><title>AI breakthrough</title><description>A new model</description>
            <link>http://example.com/1</link><guid>g1</guid></item>
      <item><title>Markets rise</title><description>Stocks up</description>
            <link>http://example.com/2</link><guid>g2</guid></item>
    </channel></rss>"""
    docs = RSSCollector.parse(xml, "http://example.com/feed")
    assert len(docs) == 2
    assert docs[0].title == "AI breakthrough"
    assert docs[0].source == "rss"
    assert docs[0].url == "http://example.com/1"


@pytest.mark.unit
def test_youtube_collector_parses_search_response():
    payload = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "Cool video",
                    "description": "desc",
                    "channelTitle": "Chan",
                    "channelId": "C1",
                    "publishedAt": "2026-01-01T00:00:00Z",
                },
            }
        ]
    }
    docs = YouTubeCollector.parse(payload)
    assert len(docs) == 1
    assert docs[0].source_id == "abc123"
    assert docs[0].url == "https://www.youtube.com/watch?v=abc123"


@pytest.mark.unit
def test_reddit_collector_parses_listing():
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "t1",
                        "title": "Ask me anything",
                        "selftext": "body",
                        "permalink": "/r/test/t1",
                        "author": "user",
                        "subreddit": "test",
                        "score": 42,
                        "created_utc": 1735689600,
                    }
                }
            ]
        }
    }
    docs = RedditCollector.parse(payload)
    assert len(docs) == 1
    assert docs[0].source == "reddit"
    assert docs[0].raw["score"] == 42
