"""Phase 6 tests: real-LLM wiring + SEO fields in Blog/YouTube generators."""

from __future__ import annotations

import json

import nlp.llm_processor as llm_mod
from content_factory.generators.blog_generator import BlogGenerator
from content_factory.generators.youtube_script_generator import (
    LONGFORM,
    SHORTS,
    YouTubeScriptGenerator,
)


class _FakeGP:
    """Fake GeminiProcessor returning a fixed completion string."""

    _resp = ""

    def __init__(self, *a, **k):
        pass

    def complete(self, prompt, as_json=False):
        return self._resp


def _patch_gp(monkeypatch, resp):
    _FakeGP._resp = resp
    monkeypatch.setattr(llm_mod, "GeminiProcessor", _FakeGP)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")


def _no_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- BlogGenerator ---------------------------------------------------------


def test_blog_template_fallback_has_seo_fields(monkeypatch):
    _no_keys(monkeypatch)
    content = BlogGenerator().generate({"name": "AI 반도체", "tags": ["AI", "칩"]}, "blog")
    assert content["generator"] == "template"
    assert content["seo_title"] and content["summary"]
    assert content["tags"] == ["AI", "칩"]
    assert content["body"]


def test_blog_gemini_path(monkeypatch):
    _patch_gp(
        monkeypatch,
        json.dumps(
            {
                "seo_title": "AI 반도체 완벽 정리",
                "title": "AI 반도체",
                "summary": "요약문",
                "body": "## 서론\n본문",
                "cta": "구독!",
                "tags": ["AI", "반도체"],
            }
        ),
    )
    content = BlogGenerator().generate({"name": "AI 반도체", "tags": ["AI"]}, "blog")
    assert content["generator"] == "gemini"
    assert content["seo_title"] == "AI 반도체 완벽 정리"
    assert content["summary"] == "요약문"
    assert content["tags"] == ["AI", "반도체"]
    assert content["hashtags"]


def test_blog_gemini_bad_json_falls_back(monkeypatch):
    _patch_gp(monkeypatch, "not json")
    content = BlogGenerator().generate({"name": "주제", "tags": []}, "blog")
    assert content["generator"] == "template"


# --- YouTubeScriptGenerator ------------------------------------------------


def test_youtube_template_has_seo_and_2col(monkeypatch):
    _no_keys(monkeypatch)
    node = {"title": "AI 칩 전쟁", "summary": "요약", "entities": [{"name": "엔비디아"}]}
    content = YouTubeScriptGenerator().generate(node, platform=SHORTS)
    assert content["generator"] == "template"
    assert content["seo_title"] and content["summary"]
    assert content["segments"][0]["section"] == "훅(3초)"
    assert content["segments"][-1]["section"] == "CTA"
    assert all({"visual", "narration"} <= set(s) for s in content["segments"])


def test_youtube_gemini_path(monkeypatch):
    _patch_gp(
        monkeypatch,
        json.dumps(
            {
                "seo_title": "엔비디아 독주",
                "summary": "칩 전쟁 요약",
                "tags": ["AI", "엔비디아"],
                "hook": "3초 훅!",
                "cta": "구독 부탁!",
                "segments": [
                    {"section": "핵심", "visual": "그래프", "narration": "대사1"},
                    {"section": "정리", "visual": "리스트", "narration": "대사2"},
                ],
            }
        ),
    )
    node = {"title": "AI 칩 전쟁", "summary": "요약", "entities": [{"name": "엔비디아"}]}
    content = YouTubeScriptGenerator().generate(node, platform=LONGFORM)
    assert content["generator"] == "gemini"
    assert content["seo_title"] == "엔비디아 독주"
    assert content["hook"] == "3초 훅!"
    # hook + 2 llm segments + CTA
    assert len(content["segments"]) == 4
    assert content["segments"][1]["narration"] == "대사1"


def test_youtube_gemini_no_segments_falls_back(monkeypatch):
    _patch_gp(monkeypatch, json.dumps({"seo_title": "x", "segments": []}))
    node = {"title": "주제", "entities": []}
    content = YouTubeScriptGenerator().generate(node, platform=SHORTS)
    assert content["generator"] == "template"
