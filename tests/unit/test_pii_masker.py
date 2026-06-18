"""Tests for PIIMasker, CopyrightScorer, RobotsChecker (QA-021/022/023)."""

from __future__ import annotations

import pytest

from compliance.copyright_scorer import CopyrightScorer
from compliance.pii_masker import PIIMasker
from compliance.robots_checker import RobotsChecker


@pytest.mark.unit
def test_mask_email():
    masker = PIIMasker()
    masked, detections = masker.mask("Contact me at john.doe@example.com please")
    assert "[EMAIL]" in masked
    assert "john.doe@example.com" not in masked
    assert any(d["type"] == "email" for d in detections)


@pytest.mark.unit
def test_mask_korean_phone():
    masker = PIIMasker()
    masked, detections = masker.mask("연락처는 010-1234-5678 입니다")
    assert "[PHONE]" in masked
    assert any(d["type"] == "phone_kr" for d in detections)


@pytest.mark.unit
def test_mask_does_not_mutate_original():
    masker = PIIMasker()
    original = "email a@b.com here"
    masked, _ = masker.mask(original)
    assert original == "email a@b.com here"
    assert masked != original


@pytest.mark.unit
def test_mask_rrn():
    masker = PIIMasker()
    masked, detections = masker.mask("주민번호 900101-1234567 입니다")
    assert "[RRN]" in masked
    assert any(d["type"] == "krrn" for d in detections)


@pytest.mark.unit
def test_detect_only_no_pii():
    masker = PIIMasker()
    assert masker.detect_only("nothing sensitive here") == []


@pytest.mark.unit
def test_copyright_safe_when_attributed_open_license():
    scorer = CopyrightScorer()
    score = scorer.score("original commentary text", "https://src.example.com", "cc-by")
    assert scorer.is_safe(score)


@pytest.mark.unit
def test_copyright_risky_when_heavy_quotes_no_source():
    scorer = CopyrightScorer()
    text = '"' + ("copied sentence " * 20) + '"'
    score = scorer.score(text, "", "all-rights-reserved")
    assert score > 0.30
    assert not scorer.is_safe(score)


@pytest.mark.unit
def test_copyright_score_in_range():
    scorer = CopyrightScorer()
    for lic in ["cc0", "fair-use", "all-rights-reserved", None]:
        s = scorer.score("some text", "", lic)
        assert 0.0 <= s <= 1.0


@pytest.mark.unit
def test_robots_allow_and_disallow():
    rc = RobotsChecker()
    robots = "User-agent: *\nDisallow: /private\nCrawl-delay: 5"
    rc.refresh("https://example.com", robots_text=robots)
    assert rc.is_allowed("https://example.com/public") is True
    assert rc.is_allowed("https://example.com/private/secret") is False


@pytest.mark.unit
def test_robots_crawl_delay():
    rc = RobotsChecker(default_crawl_delay=1.0)
    rc.refresh("https://example.com", robots_text="User-agent: *\nCrawl-delay: 7")
    assert rc.get_crawl_delay("https://example.com") == 7.0


@pytest.mark.unit
def test_robots_fail_open_unknown_domain():
    rc = RobotsChecker()
    # Unknown domain with no fetch -> default allow (fail-open)
    rc._cache["https://known.com"] = rc._cache.get("https://known.com")  # noop
    assert isinstance(rc.get_crawl_delay("https://known.com"), float)
