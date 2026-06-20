"""Unit tests for GeminiProcessor.complete() (nlp/llm_processor.py)."""

from __future__ import annotations

from nlp.llm_processor import GeminiProcessor


def test_complete_returns_empty_without_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gp = GeminiProcessor()
    assert gp.complete("hi") == ""


def test_complete_uses_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    gp = GeminiProcessor()
    monkeypatch.setattr(gp, "_call_openrouter", lambda p: "hello world")
    assert gp.complete("prompt") == "hello world"


def test_complete_strips_code_fence_when_json(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    gp = GeminiProcessor()
    monkeypatch.setattr(gp, "_call_openrouter", lambda p: '```json\n{"a": 1}\n```')
    assert gp.complete("p", as_json=True) == '{"a": 1}'


def test_complete_falls_through_backends(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gp = GeminiProcessor()
    monkeypatch.setattr(gp, "_call_openrouter", lambda p: "")
    monkeypatch.setattr(gp, "_call_gemini_sdk", lambda p: "")
    monkeypatch.setattr(gp, "_call_gemini_http", lambda p: "from-http")
    assert gp.complete("p") == "from-http"


def test_complete_returns_empty_when_all_backends_empty(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    gp = GeminiProcessor()
    monkeypatch.setattr(gp, "_call_openrouter", lambda p: "")
    monkeypatch.setattr(gp, "_call_gemini_sdk", lambda p: "")
    monkeypatch.setattr(gp, "_call_gemini_http", lambda p: "")
    assert gp.complete("p") == ""
