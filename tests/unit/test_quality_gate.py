"""Tests for QualityGate and content generators (QA-024)."""

from __future__ import annotations

import pytest

from content_factory.generators.blog_generator import BlogGenerator
from content_factory.generators.newsletter_generator import NewsletterGenerator
from content_factory.generators.short_video_generator import ShortVideoGenerator
from content_factory.quality_gate import QualityGate, flesch_kincaid_reading_ease


def _readable_content(title="A Clear Title"):
    body = (
        "The cat sat on the mat. The dog ran in the park. "
        "We like to play. The sun is up. Birds can fly high. "
        "It is a good day to walk and to talk."
    )
    return {
        "title": title,
        "body": body,
        "source_url": "https://src.example.com",
        "license": "cc-by",
    }


@pytest.mark.unit
def test_stage1_empty_body_flagged():
    qg = QualityGate()
    issues = qg.stage1_format({"title": "x", "body": ""}, "blog")
    assert any("empty body" in i for i in issues)


@pytest.mark.unit
def test_stage2_readability_range():
    qg = QualityGate()
    score = qg.stage2_readability(_readable_content())
    assert 0.0 <= score <= 100.0


@pytest.mark.unit
def test_stage3_banned_term_flagged():
    qg = QualityGate()
    issues = qg.stage3_brand_safety(
        {"body": "this is a guaranteed profit scheme", "source_url": "x"}
    )
    assert any("banned term" in i for i in issues)


@pytest.mark.unit
def test_check_passes_for_clean_readable_content():
    qg = QualityGate()
    qg.readability_min = 60.0
    passed, issues = qg.check(_readable_content(), "blog")
    assert passed, issues
    assert issues == []


@pytest.mark.unit
def test_check_fails_for_banned_and_empty():
    qg = QualityGate()
    passed, issues = qg.check({"title": "", "body": "get rich quick now"}, "blog")
    assert not passed
    assert len(issues) >= 1


@pytest.mark.unit
def test_flesch_kincaid_simple_text_is_high():
    score = flesch_kincaid_reading_ease("The cat sat. The dog ran. We had fun.")
    assert score > 60


@pytest.mark.unit
def test_blog_generator_produces_finalized_content():
    gen = BlogGenerator()
    content = gen.generate({"name": "AI", "tags": ["ai", "tech"]}, "blog")
    assert content["format"] == "blog"
    assert content["char_count"] == len(content["body"])
    assert content["token_count"] >= 0
    assert gen.validate_length(content, "blog")


@pytest.mark.unit
def test_short_video_generator_hook_and_length():
    gen = ShortVideoGenerator()
    content = gen.generate(
        {"name": "Markets", "emotion": "surprise", "tags": ["finance"]}, "shorts"
    )
    assert content["hook"].startswith("You won't believe")
    assert gen.validate_length(content, "shorts")


@pytest.mark.unit
def test_newsletter_generator_sections():
    gen = NewsletterGenerator()
    node = {"items": [{"name": f"Story {i}", "summary": "s"} for i in range(8)]}
    content = gen.generate(node, "newsletter")
    # only top 5 items rendered
    assert content["body"].count("Story") == 5
    assert content["format"] == "newsletter"
