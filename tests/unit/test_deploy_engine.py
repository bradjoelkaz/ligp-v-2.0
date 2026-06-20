"""Tests for the virtual deploy engine (publisher/deploy_engine.py)."""

from __future__ import annotations

from publisher import deploy_engine as de


class FakeStore:
    def __init__(self):
        self.records = []

    def init_db(self):
        pass

    def record_deployment(self, content_id, platform, url, status):
        self.records.append((content_id, platform, url, status))


class HealthyPublisher:
    def health_check(self):
        return True

    def publish(self, content):
        return {"url": "https://real/post/1", "post_id": "1"}


class UnhealthyPublisher:
    def health_check(self):
        return False

    def publish(self, content):  # pragma: no cover - should not be called
        raise AssertionError("publish must not run when unhealthy")


class FailingPublisher:
    def health_check(self):
        return True

    def publish(self, content):
        raise RuntimeError("network down")


def test_deploy_mock_when_no_publisher():
    store = FakeStore()
    out = de.deploy({"content_id": "c1"}, "tistory", store=store)
    assert out["status"] == "mock"
    assert out["url"] == "https://mock.local/tistory/c1"
    assert store.records[0] == ("c1", "tistory", "https://mock.local/tistory/c1", "mock")


def test_deploy_real_publisher_success():
    store = FakeStore()
    out = de.deploy({"content_id": "c2"}, "youtube", store=store, publisher=HealthyPublisher())
    assert out["status"] == "published"
    assert out["url"] == "https://real/post/1"


def test_deploy_unhealthy_publisher_falls_back_to_mock():
    store = FakeStore()
    out = de.deploy({"content_id": "c3"}, "youtube", store=store, publisher=UnhealthyPublisher())
    assert out["status"] == "mock"


def test_deploy_publish_exception_falls_back_to_mock():
    store = FakeStore()
    out = de.deploy({"content_id": "c4"}, "naver_blog", store=store, publisher=FailingPublisher())
    assert out["status"] == "mock"
    assert store.records[0][3] == "mock"


def test_deploy_derives_content_id():
    store = FakeStore()
    out = de.deploy({"format": "blog", "title": "제목"}, "wordpress", store=store)
    assert out["content_id"] == "blog:제목"


def test_resolve_publisher_unknown_platform_is_none():
    assert de._resolve_publisher("tistory") is None


def test_deploy_default_store_integration(tmp_path, monkeypatch):
    from database import db_store

    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path / "d.db"))
    out = de.deploy({"content_id": "z1"}, "tistory")  # store=None -> real db_store
    assert out["status"] == "mock"
    assert db_store.get_deployments()[0]["content_id"] == "z1"
