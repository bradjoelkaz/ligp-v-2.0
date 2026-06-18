"""YouTube Data API v3 collector (quota-aware).

Daily quota: 10,000 units (search=100, videos.list=1). Strategy: cap searches
so a day's budget is not exhausted in one run.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from ingestion.base_collector import BaseCollector, RawDocument
from utils.logger import get_logger

_log = get_logger(__name__)


class YouTubeCollector(BaseCollector):
    """YouTube Data API v3 collector."""

    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
    DAILY_UNIT_LIMIT = 10_000
    SEARCH_COST = 100
    VIDEO_COST = 1

    def __init__(self) -> None:
        super().__init__(source="youtube", rate_limit=5.0)
        self._api_key = os.getenv("YOUTUBE_API_KEY", "")
        self._units_used = 0  # in-memory (resets on restart)

    def _can_search(self) -> bool:
        return self._units_used + self.SEARCH_COST <= self.DAILY_UNIT_LIMIT

    async def search(
        self,
        query: str,
        max_results: int = 50,
        region_code: str = "KR",
        relevance_language: str = "ko",
    ) -> list[RawDocument]:
        """Search videos, then fetch details (2-step)."""
        if not self._api_key or not self._can_search():
            return []

        try:
            import httpx  # lazy

            async with httpx.AsyncClient(timeout=15.0) as client:
                search_resp = await client.get(
                    self.SEARCH_URL,
                    params={
                        "key": self._api_key,
                        "q": query,
                        "type": "video",
                        "part": "id,snippet",
                        "maxResults": min(max_results, 50),
                        "order": "date",
                        "regionCode": region_code,
                        "relevanceLanguage": relevance_language,
                    },
                )
                search_resp.raise_for_status()
                self._units_used += self.SEARCH_COST
                search_data: dict[str, Any] = search_resp.json()

                video_ids = [
                    item["id"]["videoId"]
                    for item in search_data.get("items", [])
                    if item.get("id", {}).get("kind") == "youtube#video"
                ]
                if not video_ids:
                    return []

                detail_resp = await client.get(
                    self.VIDEOS_URL,
                    params={
                        "key": self._api_key,
                        "id": ",".join(video_ids),
                        "part": "snippet,statistics,contentDetails",
                    },
                )
                detail_resp.raise_for_status()
                self._units_used += len(video_ids) * self.VIDEO_COST
                detail_data: dict[str, Any] = detail_resp.json()
        except Exception as exc:  # noqa: BLE001
            self._log_error("youtube_search_failed", str(exc))
            return []

        docs: list[RawDocument] = []
        for item in detail_data.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            published_raw = snippet.get("publishedAt", "")
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = datetime.utcnow()

            docs.append(
                RawDocument(
                    source="youtube",
                    url=f"https://youtube.com/watch?v={item['id']}",
                    title=snippet.get("title", ""),
                    body=snippet.get("description", ""),
                    author=snippet.get("channelTitle", ""),
                    published_at=published_at,
                    lang="ko",
                    raw={
                        "video_id": item["id"],
                        "view_count": int(stats.get("viewCount", 0)),
                        "like_count": int(stats.get("likeCount", 0)),
                        "comment_count": int(stats.get("commentCount", 0)),
                        "duration": item.get("contentDetails", {}).get("duration", ""),
                        **snippet,
                    },
                )
            )
        return docs

    async def get_trending(self, region_code: str = "KR") -> list[RawDocument]:
        """Collect trending videos for a region."""
        return await self.search(query="", max_results=50, region_code=region_code)

    async def health_check(self) -> bool:  # type: ignore[override]
        if not self._api_key:
            return False
        docs = await self.search(query="test", max_results=1)
        return len(docs) > 0
