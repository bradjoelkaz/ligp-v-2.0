"""YouTube collector (Layer 1) via the official YouTube Data API v3.

Uses the ``search.list`` / ``videos.list`` response shape. Network is lazy;
:meth:`parse` operates on a raw JSON dict for offline testing.
"""

from __future__ import annotations

import os
from typing import Any

from ingestion.base_collector import BaseCollector, CollectorConfig
from ingestion.schema import RawDocument
from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)


class YouTubeCollector(BaseCollector):
    def __init__(self, config: CollectorConfig | None = None):
        # YouTube Data API quota is measured in "units" (default 10,000/day).
        super().__init__(config or CollectorConfig(platform_id="youtube", api_quota_per_day=10000))

    async def fetch(
        self,
        query: str | None = None,
        max_results: int = 25,
        raw_json: dict[str, Any] | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        if raw_json is None:
            raw_json = await self._download(query, max_results)
        return [d.to_dict() for d in self.parse(raw_json)]

    async def _download(self, query: str | None, max_results: int) -> dict[str, Any]:
        if not query:
            raise ValueError("query or raw_json is required")
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if not api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not set")
        try:
            import httpx  # lazy optional import
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for live YouTube fetches") from exc
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&type=video&maxResults={max_results}"
            f"&q={query}&key={api_key}"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def parse(payload: dict[str, Any]) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            id_field = item.get("id", {})
            video_id = id_field.get("videoId", "") if isinstance(id_field, dict) else str(id_field)
            docs.append(
                RawDocument(
                    source="youtube",
                    source_id=video_id or item.get("etag", ""),
                    title=normalize_text(snippet.get("title", "")),
                    text=normalize_text(snippet.get("description", "")),
                    url=f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
                    author=snippet.get("channelTitle", ""),
                    published_at=snippet.get("publishedAt", ""),
                    raw={"channel_id": snippet.get("channelId", "")},
                )
            )
        return docs
