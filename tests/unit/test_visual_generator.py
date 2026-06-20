"""Mock-based tests for the visual generator (content_factory/visual_generator.py)."""

from __future__ import annotations

from content_factory.visual_generator import VisualGenerator, default_image


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class _HTTP:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def post(self, url, json=None, headers=None):
        self.calls += 1
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def test_default_image_category_mapping():
    assert default_image("IT/테크").endswith("tech.png")
    assert default_image("unknown").endswith("trend.png")


def test_no_api_key_returns_category_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gen = VisualGenerator()
    assert not gen.available()
    out = gen.generate_image("cozy room", "비즈니스")
    assert out["status"] == "fallback"
    assert out["reason"] == "no_api_key"
    assert out["image_url"].endswith("business.png")


def test_generate_returns_hosted_url():
    gen = VisualGenerator(api_key="k")
    http = _HTTP(_Resp({"images": [{"url": "https://cdn/img.png"}]}))
    out = gen.generate_image("a cat", "IT/테크", http=http)
    assert out["status"] == "complete"
    assert out["image_url"] == "https://cdn/img.png"


def test_generate_saves_base64_via_writer():
    gen = VisualGenerator(api_key="k")
    data = {"candidates": [{"content": {"parts": [{"inline_data": {"data": "QkFTRTY0"}}]}}]}
    http = _HTTP(_Resp(data))
    saved = {}

    def writer(b64, seed):
        saved["b64"] = b64
        return "/data/images/abc.png"

    out = gen.generate_image("art", "문화/라이프", http=http, writer=writer, content_id="c1")
    assert out["status"] == "complete"
    assert out["image_url"] == "/data/images/abc.png"
    assert saved["b64"] == "QkFTRTY0"


def test_generate_no_image_in_response_falls_back():
    gen = VisualGenerator(api_key="k")
    out = gen.generate_image("x", "사회/종합", http=_HTTP(_Resp({"candidates": []})))
    assert out["status"] == "fallback" and out["reason"] == "no_image_in_response"
    assert out["image_url"].endswith("society.png")


def test_generate_http_error_falls_back():
    gen = VisualGenerator(api_key="k")
    out = gen.generate_image("x", "IT/테크", http=_HTTP(RuntimeError("429 quota")))
    assert out["status"] == "fallback"
    assert "429" in out["reason"]
    assert out["image_url"].endswith("tech.png")
