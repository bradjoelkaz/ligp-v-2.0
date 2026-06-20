"""Tests for the newsletter digest generator + publisher (Phase 12)."""

from __future__ import annotations

from content_factory.generators.newsletter_generator import NewsletterGenerator
from publisher import newsletter_publisher as np

_TOPICS = [
    {
        "title": "AI 반도체",
        "summary": "엔비디아 경쟁",
        "category": "IT/테크",
        "title_en": "AI chips",
        "summary_en": "Nvidia race",
    },
    {"title": "금리 인하", "summary": "연준 발표", "category": "비즈니스"},
]


# --- digest generator ------------------------------------------------------


def test_build_digest_html_and_markdown():
    nl = NewsletterGenerator().build_digest(_TOPICS, title="데일리")
    assert nl["format"] == "newsletter"
    assert nl["item_count"] == 2
    assert "<h1>" in nl["html"] and "AI 반도체" in nl["html"]
    assert nl["markdown"].startswith("# 데일리")
    assert "AI 반도체" in nl["markdown"]
    assert nl["language"] == "ko"


def test_build_digest_english_prefers_translation():
    nl = NewsletterGenerator().build_digest(_TOPICS, english=True)
    assert "AI chips" in nl["html"]
    # second topic has no translation -> falls back to Korean
    assert "금리 인하" in nl["html"]
    assert nl["language"] == "en"


def test_build_digest_escapes_html():
    nl = NewsletterGenerator().build_digest([{"title": "<script>", "summary": "a & b"}])
    assert "<script>" not in nl["html"]
    assert "&lt;script&gt;" in nl["html"]
    assert "&amp;" in nl["html"]


def test_build_digest_empty_topics():
    nl = NewsletterGenerator().build_digest([])
    assert nl["item_count"] == 0
    assert "<h1>" in nl["html"]


# --- publisher -------------------------------------------------------------


class FakeStore:
    def __init__(self):
        self.records = []

    def init_db(self):
        pass

    def record_deployment(self, content_id, platform, url, status):
        self.records.append((content_id, platform, url, status))


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http")

    def json(self):
        return self._p


class _HTTP:
    def __init__(self, resp):
        self._resp = resp

    def post(self, url, headers=None, json=None):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def test_publish_mock_without_credentials(monkeypatch):
    monkeypatch.delenv("SUBSTACK_API_KEY", raising=False)
    monkeypatch.delenv("MAILCHIMP_API_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    store = FakeStore()
    out = np.publish({"content_id": "nl1", "title": "T"}, store=store)
    assert out["status"] == "mock"
    assert out["platform"] == "newsletter"
    assert store.records[0][1] == "newsletter"


def test_publish_remote_success(monkeypatch):
    monkeypatch.setenv("SUBSTACK_API_KEY", "k")
    store = FakeStore()
    http = _HTTP(_Resp({"url": "https://sub/post/1", "id": "1"}))
    out = np.publish(
        {"content_id": "nl2", "title": "T", "html": "<p>x</p>"}, store=store, http=http
    )
    assert out["status"] == "published"
    assert out["url"] == "https://sub/post/1"
    assert out["provider"] == "substack"


def test_publish_remote_failure_falls_back(monkeypatch):
    monkeypatch.setenv("MAILCHIMP_API_KEY", "k")
    monkeypatch.delenv("APP_ENV", raising=False)
    store = FakeStore()
    out = np.publish(
        {"content_id": "nl3", "title": "T"}, store=store, http=_HTTP(RuntimeError("down"))
    )
    assert out["status"] == "mock"  # dev mode -> fallback to mock


def test_publish_production_no_creds_records_failed(monkeypatch):
    monkeypatch.delenv("SUBSTACK_API_KEY", raising=False)
    monkeypatch.delenv("MAILCHIMP_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("IIGP_ALLOW_MOCK", raising=False)
    store = FakeStore()
    out = np.publish({"content_id": "nl4", "title": "T"}, store=store)
    assert out["status"] == "failed"
    assert store.records[0][3] == "failed"
