"""Tests for the multilingual translator (nlp/translator.py)."""

from __future__ import annotations

from nlp.translator import Translator


class FakeProc:
    def __init__(self, openrouter_key="", api_key="", out=""):
        self.openrouter_key = openrouter_key
        self.api_key = api_key
        self._out = out
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        if isinstance(self._out, Exception):
            raise self._out
        return self._out


def test_unavailable_without_keys_passthrough():
    t = Translator(processor=FakeProc())
    assert t.available() is False
    assert t.translate("안녕하세요") == "안녕하세요"


def test_translate_uses_llm():
    t = Translator(processor=FakeProc(openrouter_key="x", out="  Hello world  "))
    assert t.translate("안녕 세상") == "Hello world"


def test_translate_empty_passthrough():
    t = Translator(processor=FakeProc(api_key="x", out="X"))
    assert t.translate("   ") == "   "


def test_translate_error_falls_back_to_source():
    t = Translator(processor=FakeProc(api_key="x", out=RuntimeError("boom")))
    assert t.translate("원문") == "원문"


def test_translate_empty_llm_output_falls_back():
    t = Translator(processor=FakeProc(api_key="x", out="   "))
    assert t.translate("원문") == "원문"


def test_needs_translation():
    t = Translator(processor=FakeProc(api_key="x"))
    assert t.needs_translation({"language": "ko"}, "newsletter") is True
    assert t.needs_translation({"language": "en"}, "newsletter") is False
    assert t.needs_translation({"language": "ko"}, "blog") is False


def test_translate_topic_sets_english_fields():
    t = Translator(processor=FakeProc(openrouter_key="x", out="EN"))
    out = t.translate_topic({"title": "제목", "summary": "요약"})
    assert out["title_en"] == "EN"
    assert out["summary_en"] == "EN"
    assert out["translated"] is True
    # original preserved
    assert out["title"] == "제목"


def test_translate_topic_passthrough_when_unavailable():
    t = Translator(processor=FakeProc())
    out = t.translate_topic({"title": "제목", "summary": "요약"})
    assert out["title_en"] == "제목"
    assert out["translated"] is False
