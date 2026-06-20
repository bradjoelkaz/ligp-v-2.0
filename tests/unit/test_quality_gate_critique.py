"""Tests for the activated LLM self-critique stage (quality_gate.stage4)."""

from __future__ import annotations

import json

import nlp.llm_processor as llm_mod
from content_factory.quality_gate import QualityGate


class _FakeGP:
    _resp = ""

    def __init__(self, *a, **k):
        pass

    def complete(self, prompt, as_json=False):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def _patch(monkeypatch, resp):
    _FakeGP._resp = resp
    monkeypatch.setattr(llm_mod, "GeminiProcessor", _FakeGP)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")


CONTENT = {"title": "제목", "body": "충분히 긴 본문 내용입니다. " * 10}


def test_stage4_noop_without_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert QualityGate().stage4_llm_critique(dict(CONTENT)) == []


def test_stage4_rejects_low_score(monkeypatch):
    _patch(monkeypatch, json.dumps({"score": 55, "reason": "가독성 낮음"}))
    content = dict(CONTENT)
    issues = QualityGate().stage4_llm_critique(content)
    assert issues and "55" in issues[0]
    assert content["llm_critique"]["score"] == 55


def test_stage4_passes_high_score(monkeypatch):
    _patch(monkeypatch, json.dumps({"score": 92, "reason": "좋음"}))
    assert QualityGate().stage4_llm_critique(dict(CONTENT)) == []


def test_stage4_empty_body_noop(monkeypatch):
    _patch(monkeypatch, json.dumps({"score": 10}))
    assert QualityGate().stage4_llm_critique({"title": "t", "body": "   "}) == []


def test_stage4_fails_open_on_bad_json(monkeypatch):
    _patch(monkeypatch, "not-json")
    assert QualityGate().stage4_llm_critique(dict(CONTENT)) == []


def test_stage4_fails_open_on_exception(monkeypatch):
    _patch(monkeypatch, RuntimeError("boom"))
    assert QualityGate().stage4_llm_critique(dict(CONTENT)) == []


def test_stage4_empty_completion_noop(monkeypatch):
    _patch(monkeypatch, "")
    assert QualityGate().stage4_llm_critique(dict(CONTENT)) == []


def test_check_integrates_stage4(monkeypatch):
    """check() must surface a stage-4 rejection (stages 1-3 stubbed clean)."""
    _patch(monkeypatch, json.dumps({"score": 40, "reason": "비속어 포함"}))
    gate = QualityGate()
    monkeypatch.setattr(gate, "stage1_format", lambda c, p: [])
    monkeypatch.setattr(gate, "stage2_readability", lambda c: 95.0)
    monkeypatch.setattr(gate, "stage3_brand_safety", lambda c: [])
    passed, issues = gate.check(dict(CONTENT), "blog")
    assert passed is False
    assert any("critique score" in i for i in issues)
