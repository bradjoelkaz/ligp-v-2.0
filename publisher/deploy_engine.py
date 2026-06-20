"""Multi-channel virtual deploy engine (Phase 7, Layer 10/6 bridge).

Deploys generated content (blog posts, YouTube scripts) to social platforms.
Real channel publishers (Naver Blog, YouTube) are used when credentials are
configured; otherwise \u2014 or on any failure \u2014 the engine returns a deterministic
**mock** success so the pipeline keeps working offline. Every attempt is logged
to the SQLite ``deployments`` ledger.

Pure-Python with injectable ``store`` / ``publisher`` for offline unit testing.
"""

from __future__ import annotations

from typing import Any, Protocol

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


class _Publisher(Protocol):
    def publish(self, content: dict[str, Any]) -> dict[str, Any]: ...

    def health_check(self) -> bool: ...


# Platforms with a real publisher channel; others always deploy as mock.
_REAL_PUBLISHERS: dict[str, str] = {
    "naver_blog": "publisher.channels.naver_blog:NaverBlogPublisher",
    "youtube": "publisher.channels.youtube:YouTubePublisher",
}

# Platforms accepted for (mock) deployment of text/script content.
SUPPORTED_PLATFORMS = ("tistory", "wordpress", "naver_blog", "youtube", "blog")


def _resolve_publisher(platform: str) -> _Publisher | None:
    """Instantiate the real publisher for a platform, or None if unavailable."""
    target = _REAL_PUBLISHERS.get(platform)
    if not target:
        return None
    module_path, _, cls_name = target.partition(":")
    try:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, cls_name)()
    except Exception as exc:  # noqa: BLE001 - fall back to mock
        _log.warning("publisher_resolve_failed", extra={"platform": platform, "error": str(exc)})
        return None


def _mock_result(platform: str, content_id: str) -> dict[str, Any]:
    return {
        "url": f"https://mock.local/{platform}/{content_id}",
        "status": "mock",
        "published_at": utcnow_iso(),
    }


def _unavailable_result(platform: str, content_id: str, reason: str) -> dict[str, Any]:
    """Result when no real publish happened.

    Outside production this degrades to a mock success (offline-friendly); in
    production mocks are disabled, so it records a real ``failed`` status with
    the reason instead of fabricating a success.
    """
    from utils.runtime import mock_allowed

    if mock_allowed():
        return _mock_result(platform, content_id)
    _log.error("deploy_failed_production", extra={"platform": platform, "reason": reason})
    return {"url": "", "status": "failed", "error": reason, "published_at": utcnow_iso()}


def _content_id(content: dict[str, Any]) -> str:
    return str(
        content.get("content_id")
        or f"{content.get('format', 'content')}:{content.get('title', '')}"
    )


def deploy(
    content: dict[str, Any],
    platform: str,
    *,
    store: Any | None = None,
    publisher: _Publisher | None = None,
) -> dict[str, Any]:
    """Deploy ``content`` to ``platform``; record + return the result.

    Uses a real publisher when one is available and healthy; otherwise returns a
    mock success. Never raises \u2014 publish failures degrade to a mock result.
    """
    if store is None:
        from database import db_store as store

        store.init_db()

    content_id = _content_id(content)
    pub = publisher if publisher is not None else _resolve_publisher(platform)

    if pub is not None:
        try:
            if pub.health_check():
                result = dict(pub.publish(content))
                result.setdefault("status", "published")
                result.setdefault("published_at", utcnow_iso())
            else:
                result = _unavailable_result(platform, content_id, "publisher_unhealthy")
        except Exception as exc:  # noqa: BLE001 - publish failed
            _log.warning("deploy_publish_failed", extra={"platform": platform, "error": str(exc)})
            result = _unavailable_result(platform, content_id, str(exc))
    else:
        result = _unavailable_result(platform, content_id, "no_publisher_configured")

    store.record_deployment(content_id, platform, result.get("url", ""), result["status"])
    out = {"content_id": content_id, "platform": platform, **result}
    _log.info(
        "deployed_content",
        extra={"content_id": content_id, "platform": platform, "status": result["status"]},
    )
    return out
