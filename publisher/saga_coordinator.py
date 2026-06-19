"""Saga coordinator for multi-step publishing (QA-026 / DD-011).

State machine: pending -> publishing -> published | failed | compensating.
On failure the coordinator retries up to ``max_retries`` then runs the
publisher's compensation (delete) to roll back partial state.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Protocol

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


class SagaStatus(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    COMPENSATING = "compensating"


class Publisher(Protocol):
    """Minimal publisher interface the coordinator drives."""

    def publish(self, content: dict[str, Any]) -> dict[str, Any]: ...

    def delete(self, post_id: str) -> bool: ...


class SagaCoordinator:
    """Coordinate a publish with retry + compensation."""

    def __init__(self, publishers: dict[str, Publisher], max_retries: int = 3) -> None:
        self.publishers = publishers
        self.max_retries = max_retries
        self._sagas: dict[str, dict[str, Any]] = {}

    def _new_saga(self, platform: str) -> dict[str, Any]:
        saga_id = str(uuid.uuid4())
        saga = {
            "saga_id": saga_id,
            "status": SagaStatus.PENDING.value,
            "platform": platform,
            "published_url": None,
            "post_id": None,
            "error": None,
            "attempts": 0,
            "created_at": utcnow_iso(),
        }
        self._sagas[saga_id] = saga
        return saga

    def execute(self, content: dict[str, Any], platform: str) -> dict[str, Any]:
        """Publish ``content`` to ``platform`` with retries and compensation."""
        saga = self._new_saga(platform)
        publisher = self.publishers.get(platform)
        if publisher is None:
            saga["status"] = SagaStatus.FAILED.value
            saga["error"] = f"no publisher for platform: {platform}"
            return saga

        saga["status"] = SagaStatus.PUBLISHING.value
        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            saga["attempts"] = attempt
            try:
                result = publisher.publish(content)
                saga["status"] = SagaStatus.PUBLISHED.value
                saga["published_url"] = result.get("url")
                saga["post_id"] = result.get("post_id") or result.get("video_id")
                saga["error"] = None
                return saga
            except Exception as exc:  # noqa: BLE001 - publishing must not crash pipeline
                last_error = str(exc)
                _log.warning(
                    "publish_attempt_failed",
                    extra={"saga_id": saga["saga_id"], "attempt": attempt, "error": last_error},
                )

        # All retries exhausted -> compensate and mark failed.
        saga["error"] = last_error
        self.compensate(saga["saga_id"])
        saga["status"] = SagaStatus.FAILED.value
        return saga

    def compensate(self, saga_id: str) -> None:
        """Roll back any partial publish for the saga."""
        saga = self._sagas.get(saga_id)
        if saga is None:
            return
        saga["status"] = SagaStatus.COMPENSATING.value
        publisher = self.publishers.get(saga["platform"])
        post_id = saga.get("post_id")
        if publisher is not None and post_id:
            try:
                publisher.delete(post_id)
                _log.info("compensation_done", extra={"saga_id": saga_id, "post_id": post_id})
            except Exception as exc:  # pragma: no cover
                _log.error("compensation_failed", extra={"saga_id": saga_id, "error": str(exc)})

    def get_status(self, saga_id: str) -> dict[str, Any]:
        return self._sagas.get(saga_id, {"saga_id": saga_id, "status": "unknown"})
