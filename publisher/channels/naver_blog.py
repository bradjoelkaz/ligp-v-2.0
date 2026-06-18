"""Naver Blog publisher channel (Layer 10).

Implements the publisher interface used by the Saga coordinator. The HTTP client
is imported lazily; without credentials it raises so the Saga can compensate.
Rate-limit/backoff is governed upstream by the collector/quota config.
"""

from __future__ import annotations

import os
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


class NaverBlogPublisher:
    """Publish/delete posts on Naver Blog."""

    def __init__(self) -> None:
        self.base_url = os.environ.get("NAVER_BLOG_API_URL", "https://openapi.naver.com/blog")

    def _client(self):  # pragma: no cover - network path
        import httpx

        token = os.environ.get("NAVER_BLOG_TOKEN")
        if not token:
            raise RuntimeError("NAVER_BLOG_TOKEN is not set")
        return httpx.Client(
            timeout=20.0, headers={"Authorization": f"Bearer {token}", "User-Agent": "iigp/2.0"}
        )

    def publish(self, content: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - network
        with self._client() as client:
            resp = client.post(
                f"{self.base_url}/write",
                json={"title": content.get("title", ""), "contents": content.get("body", "")},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "url": data.get("url", ""),
                "post_id": data.get("logNo", ""),
                "published_at": utcnow_iso(),
            }

    def delete(self, post_id: str) -> bool:  # pragma: no cover - network
        with self._client() as client:
            resp = client.post(f"{self.base_url}/delete", json={"logNo": post_id})
            return resp.status_code == 200

    def health_check(self) -> bool:
        return bool(os.environ.get("NAVER_BLOG_TOKEN"))
