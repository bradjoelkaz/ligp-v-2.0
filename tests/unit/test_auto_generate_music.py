"""Tests for the opt-in AUTO_GENERATE_MUSIC pipeline hook (daily_pipeline)."""

from __future__ import annotations

import content_factory.suno_generator as suno_mod
from orchestration.flows import daily_pipeline as dp


class FakeStore:
    def __init__(self):
        self.saved = []

    def init_db(self):
        pass

    def save_generated_content(self, content):
        self.saved.append(content)
        return content["content_id"]


class _FakeSuno:
    def __init__(self, *a, **k):
        pass

    def generate(self, prompt, image_prompt="", **kwargs):
        return {"status": "complete", "audio_url": "https://cdn/a.mp3"}


_TOPICS = [
    {"title": "토픽1", "suno_prompt": "[LoFi] chill", "image_prompt": "cover1"},
    {"title": "토픽2", "suno_prompt": "[Ambient] calm", "image_prompt": "cover2"},
]


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_GENERATE_MUSIC", raising=False)
    assert dp.auto_generate_music(_TOPICS, store=FakeStore()) == 0


def test_enabled_generates_and_persists(monkeypatch):
    monkeypatch.setenv("AUTO_GENERATE_MUSIC", "1")
    monkeypatch.setattr(suno_mod, "SunoGenerator", _FakeSuno)
    store = FakeStore()
    n = dp.auto_generate_music(_TOPICS, store=store, limit=5)
    assert n == 2
    assert len(store.saved) == 2
    assert store.saved[0]["audio_url"] == "https://cdn/a.mp3"
    assert store.saved[0]["format"] == "suno_music"


def test_respects_limit(monkeypatch):
    monkeypatch.setenv("AUTO_GENERATE_MUSIC", "true")
    monkeypatch.setattr(suno_mod, "SunoGenerator", _FakeSuno)
    store = FakeStore()
    assert dp.auto_generate_music(_TOPICS, store=store, limit=1) == 1


def test_skips_topics_without_prompt(monkeypatch):
    monkeypatch.setenv("AUTO_GENERATE_MUSIC", "on")
    monkeypatch.setattr(suno_mod, "SunoGenerator", _FakeSuno)
    store = FakeStore()
    n = dp.auto_generate_music([{"title": ""}], store=store)
    assert n == 0
