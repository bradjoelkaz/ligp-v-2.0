"""Integration test: full offline pipeline (Layer 15).

Drives ``run_daily_pipeline`` end-to-end with mock documents and asserts at
least one quality-checked content item is produced.
"""

from __future__ import annotations

import pytest

# ── Guard: orchestration flows pull in config_loader / collector helpers whose
# optional deps may be absent in a dependency-light environment. These guards
# make the module skip cleanly there; in CI (requirements-dev installs both)
# the tests run normally.
pytest.importorskip("yaml")  # config_loader
pytest.importorskip("httpx")  # collector helpers

from orchestration.flows.daily_pipeline import run_daily_pipeline  # noqa: E402
from orchestration.flows.realtime_ingestion import run_realtime_ingestion  # noqa: E402


@pytest.mark.integration
def test_full_pipeline_produces_content():
    documents = [
        {
            "source_id": "d1",
            "title": "OpenAI releases new model",
            "text": "OpenAI and NVIDIA announce a major AI breakthrough in California.",
        },
        {
            "source_id": "d2",
            "title": "Markets rally on tech earnings",
            "text": "Technology stocks surged after strong quarterly results.",
        },
        {
            "source_id": "d3",
            "title": "Travel trends for 2026",
            "text": "Tourists flock to new destinations across Asia and Europe.",
        },
        # exact duplicate of d1 -> should be removed by dedup
        {
            "source_id": "d4",
            "title": "OpenAI releases new model",
            "text": "OpenAI and NVIDIA announce a major AI breakthrough in California.",
        },
    ]
    summary = run_daily_pipeline(documents, platform="blog", top_k=5)

    assert summary["ingested"] == 4
    assert summary["unique"] == 3  # one duplicate removed
    assert summary["graph_nodes"] >= 12  # seeds + new topic/entity nodes
    assert summary["candidates"] >= 1
    assert len(summary["generated"]) >= 1
    # each generated item is finalized blog content
    for item in summary["generated"]:
        assert item["format"] == "blog"
        assert "quality_passed" in item


@pytest.mark.integration
def test_realtime_ingestion_dedup():
    docs = [
        {"source_id": "r1", "title": "Breaking news item", "text": "something happened"},
        {"source_id": "r2", "title": "Breaking news item", "text": "something happened"},
        {"source_id": "r3", "title": "A different story", "text": "unrelated content here"},
    ]
    result = run_realtime_ingestion(docs)
    assert result["received"] == 3
    assert result["added"] == 2  # one duplicate filtered


@pytest.mark.integration
def test_realtime_ingestion_handles_empty_input():
    """Empty input returns a well-formed, empty result without error."""
    result = run_realtime_ingestion(documents=[])
    assert result is not None
    assert result["received"] == 0
    assert result["added"] == 0


@pytest.mark.integration
def test_pipeline_handles_duplicate_documents():
    """Duplicate documents are de-duplicated before processing."""
    doc = {
        "source_id": "dup-1",
        "title": "Duplicate test",
        "text": "Same document submitted twice for deduplication check.",
    }
    summary = run_daily_pipeline(documents=[doc, doc])
    assert summary is not None
    assert summary["ingested"] == 2
    assert summary["unique"] == 1  # the duplicate is removed


@pytest.mark.integration
def test_pipeline_with_korean_content():
    """Korean-language documents are processed end-to-end without error."""
    documents = [
        {
            "source_id": "ko-1",
            "title": "AI 기술 동향",
            "text": "인공지능 기술이 빠르게 발전하고 있으며 산업 전반에 영향을 미치고 있다.",
        },
    ]
    summary = run_daily_pipeline(documents=documents)
    assert summary is not None
    assert summary["ingested"] == 1
    assert summary["graph_nodes"] >= 12  # seed nodes + the new topic node
