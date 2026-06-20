"""Mock-based tests for the Suno Pro session generator (content_factory/suno_generator.py)."""

from __future__ import annotations

from content_factory.suno_generator import FALLBACK_MESSAGE, SunoGenerator


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeHTTP:
    """Scripted httpx-like client: one POST response, then queued feed GETs."""

    def __init__(self, post_resp, feed_responses):
        self._post = post_resp
        self._feeds = list(feed_responses)
        self.post_calls = 0
        self.get_calls = 0

    def post(self, url, json=None, headers=None):
        self.post_calls += 1
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    def get(self, url, params=None, headers=None):
        self.get_calls += 1
        return self._feeds.pop(0)


def _no_sleep(_):
    return None


def test_no_cookie_returns_fallback(monkeypatch):
    monkeypatch.delenv("SUNO_COOKIE", raising=False)
    gen = SunoGenerator()
    assert not gen.available()
    out = gen.generate("lofi chill", "cozy room")
    assert out["status"] == "fallback"
    assert out["reason"] == "no_cookie"
    assert out["suno_prompt"] == "lofi chill"
    assert out["message"] == FALLBACK_MESSAGE


def test_generate_complete_after_polling():
    gen = SunoGenerator(cookie="session=abc")
    http = FakeHTTP(
        post_resp=_Resp({"clips": [{"id": "clip1"}, {"id": "clip2"}]}),
        feed_responses=[
            _Resp([{"id": "clip1", "status": "submitted"}]),  # not ready yet
            _Resp(
                [
                    {
                        "id": "clip1",
                        "status": "complete",
                        "audio_url": "https://cdn/audio.mp3",
                        "image_large_url": "https://cdn/cover.png",
                    }
                ]
            ),
        ],
    )
    out = gen.generate("lofi", "cover", http=http, sleep=_no_sleep, poll_interval=0)
    assert out["status"] == "complete"
    assert out["audio_url"] == "https://cdn/audio.mp3"
    assert out["image_url"] == "https://cdn/cover.png"
    assert out["clip_id"] == "clip1"
    assert http.get_calls == 2


def test_generate_no_clip_ids_falls_back():
    gen = SunoGenerator(cookie="session=abc")
    http = FakeHTTP(post_resp=_Resp({"clips": []}), feed_responses=[])
    out = gen.generate("lofi", http=http, sleep=_no_sleep)
    assert out["status"] == "fallback" and out["reason"] == "no_clip_ids"


def test_generate_timeout_falls_back():
    gen = SunoGenerator(cookie="session=abc")
    feeds = [_Resp([{"id": "c1", "status": "submitted"}]) for _ in range(3)]
    http = FakeHTTP(post_resp=_Resp({"clips": [{"id": "c1"}]}), feed_responses=feeds)
    out = gen.generate("lofi", http=http, sleep=_no_sleep, max_polls=3, poll_interval=0)
    assert out["status"] == "fallback" and out["reason"] == "timeout"


def test_generate_http_error_falls_back():
    gen = SunoGenerator(cookie="session=abc")
    http = FakeHTTP(post_resp=RuntimeError("cookie expired"), feed_responses=[])
    out = gen.generate("lofi", "img", http=http, sleep=_no_sleep)
    assert out["status"] == "fallback"
    assert "cookie expired" in out["reason"]
    assert out["image_prompt"] == "img"


def test_cookie_from_env(monkeypatch):
    monkeypatch.setenv("SUNO_COOKIE", "session=fromenv")
    assert SunoGenerator().available() is True
