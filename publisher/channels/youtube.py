"""YouTube publisher channel (Layer 10).

Uploads video metadata via the YouTube Data API v3 (lazy client). Implements
the publisher interface (publish/delete/health_check) for the Saga coordinator.
"""

from __future__ import annotations

import os
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


class YouTubePublisher:
    """Publish/delete YouTube uploads."""

    def __init__(self) -> None:
        self.api_base = "https://www.googleapis.com/youtube/v3"

    def _token(self) -> str:
        token = os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN") or os.environ.get("YOUTUBE_API_KEY")
        if not token:
            raise RuntimeError("YouTube credentials are not set")
        return token

    def publish(self, content: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - network
        import httpx

        token = self._token()
        with httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {token}"}) as client:
            resp = client.post(
                f"{self.api_base}/videos?part=snippet,status",
                json={
                    "snippet": {
                        "title": content.get("title", ""),
                        "description": content.get("body", ""),
                        "tags": content.get("tags", []),
                    },
                    "status": {"privacyStatus": "public"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            vid = data.get("id", "")
            return {
                "url": f"https://www.youtube.com/watch?v={vid}",
                "video_id": vid,
                "published_at": utcnow_iso(),
            }

    def delete(self, video_id: str) -> bool:  # pragma: no cover - network
        import httpx

        token = self._token()
        with httpx.Client(timeout=20.0, headers={"Authorization": f"Bearer {token}"}) as client:
            resp = client.delete(f"{self.api_base}/videos?id={video_id}")
            return resp.status_code in (200, 204)

    def health_check(self) -> bool:
        return bool(
            os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN") or os.environ.get("YOUTUBE_API_KEY")
        )
