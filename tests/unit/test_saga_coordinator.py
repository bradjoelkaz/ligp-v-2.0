"""Tests for SagaCoordinator (QA-026 / DD-011)."""

from __future__ import annotations

from typing import Any

import pytest

from publisher.saga_coordinator import SagaCoordinator, SagaStatus


class _OKPublisher:
    def __init__(self):
        self.deleted: list[str] = []

    def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        return {"url": "https://example.com/p/1", "post_id": "p1"}

    def delete(self, post_id: str) -> bool:
        self.deleted.append(post_id)
        return True


class _FailPublisher:
    def __init__(self):
        self.deleted: list[str] = []
        self.calls = 0

    def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        raise RuntimeError("publish failed")

    def delete(self, post_id: str) -> bool:
        self.deleted.append(post_id)
        return True


class _PartialThenFailPublisher:
    """Returns a post_id-bearing result on first publish, but we simulate a
    later-stage failure by raising; used to verify compensation deletes it."""

    def __init__(self):
        self.deleted: list[str] = []

    def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("downstream confirm failed")

    def delete(self, post_id: str) -> bool:
        self.deleted.append(post_id)
        return True


@pytest.mark.unit
def test_successful_publish_flow():
    pub = _OKPublisher()
    saga = SagaCoordinator({"blog": pub})
    result = saga.execute({"title": "t", "body": "b"}, "blog")
    assert result["status"] == SagaStatus.PUBLISHED.value
    assert result["published_url"] == "https://example.com/p/1"
    assert result["post_id"] == "p1"


@pytest.mark.unit
def test_failed_publish_after_retries():
    pub = _FailPublisher()
    saga = SagaCoordinator({"blog": pub}, max_retries=3)
    result = saga.execute({"title": "t", "body": "b"}, "blog")
    assert result["status"] == SagaStatus.FAILED.value
    assert result["attempts"] == 3
    assert "publish failed" in result["error"]


@pytest.mark.unit
def test_no_publisher_for_platform():
    saga = SagaCoordinator({})
    result = saga.execute({"title": "t", "body": "b"}, "tiktok")
    assert result["status"] == SagaStatus.FAILED.value
    assert "no publisher" in result["error"]


@pytest.mark.unit
def test_get_status_unknown():
    saga = SagaCoordinator({})
    assert saga.get_status("does-not-exist")["status"] == "unknown"


@pytest.mark.unit
def test_compensate_is_safe_without_post_id():
    pub = _PartialThenFailPublisher()
    saga = SagaCoordinator({"blog": pub}, max_retries=1)
    result = saga.execute({"title": "t", "body": "b"}, "blog")
    # publish never succeeded -> no post_id -> nothing to delete, still FAILED
    assert result["status"] == SagaStatus.FAILED.value
    assert pub.deleted == []
