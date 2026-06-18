"""BlogGenerator unit tests (offline / template fallback)."""

from __future__ import annotations

import asyncio
import os

import pytest


@pytest.mark.unit
def test_template_fallback_no_api_key():
    os.environ.pop("OPENAI_API_KEY", None)
    from content_factory.generators.blog_generator import BlogGenerator

    gen = BlogGenerator()
    node = {"label": "테스트 주제", "emotion": "joy", "tags": ["tag1", "tag2"]}
    result = asyncio.run(gen.generate_async(node, "naver_blog"))
    assert result["generator"] == "template"
    assert len(result["title"]) > 0
    assert result["platform"] == "naver_blog"
    assert result["format"] == "blog"
    assert result["char_count"] == len(result["body"])
    assert result["token_count"] >= 0


@pytest.mark.unit
def test_budget_gate():
    os.environ["OPENAI_API_KEY"] = "fake-key"
    from content_factory.generators.blog_generator import BlogGenerator

    gen = BlogGenerator()
    gen._cost_this_month = 9999.0  # force over budget
    assert not gen._budget_ok()


@pytest.mark.unit
def test_validate_length_within_limit():
    from content_factory.generators.blog_generator import BlogGenerator

    gen = BlogGenerator()
    assert gen.validate_length({"body": "a" * 100}, "naver_blog") is True


@pytest.mark.unit
def test_validate_length_exceeds_limit():
    from content_factory.generators.blog_generator import BlogGenerator

    gen = BlogGenerator()
    assert gen.validate_length({"body": "a" * 11000}, "naver_blog") is False


@pytest.mark.unit
def test_generate_sync_wrapper():
    os.environ.pop("OPENAI_API_KEY", None)
    from content_factory.generators.blog_generator import BlogGenerator

    gen = BlogGenerator()
    result = gen.generate({"name": "AI", "tags": ["ai"]}, "blog")
    assert result["format"] == "blog"
    assert gen.validate_length(result, "blog")
