"""Reddit collector (Layer 1) via the official JSON API.

Reads listing JSON (e.g. ``https://oauth.reddit.com/r/<sub>/hot``). Network and
auth are handled lazily; :meth:`parse` works on a raw JSON dict for offline
testing.
"""

from __future__ import annotations

import os
from datetime import UTC
from typing import Any

from ingestion.base_collector import BaseCollector, CollectorConfig
from ingestion.schema import RawDocument
from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)


class RedditCollector(BaseCollector):
    def __init__(self, config: CollectorConfig | None = None):
        super().__init__(config or CollectorConfig(platform_id="reddit", api_quota_per_day=10000))

    async def fetch(
        self,
        subreddit: str | None = None,
        listing: str = "hot",
        limit: int = 50,
        raw_json: dict[str, Any] | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        if raw_json is None:
            raw_json = await self._download(subreddit, listing, limit)
        return [d.to_dict() for d in self.parse(raw_json)]

    async def _download(self, subreddit: str | None, listing: str, limit: int) -> dict[str, Any]:
        if not subreddit:
            raise ValueError("subreddit or raw_json is required")
        try:
            import httpx  # lazy optional import
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for live Reddit fetches") from exc
        token = os.environ.get("REDDIT_ACCESS_TOKEN", "")
        ua = os.environ.get("REDDIT_USER_AGENT", "iigp/2.0")
        base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
        headers = {"User-Agent": ua}
        if token:
            headers["Authorization"] = f"bearer {token}"
        url = f"{base}/r/{subreddit}/{listing}.json?limit={limit}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def parse(payload: dict[str, Any]) -> list[RawDocument]:
        docs: list[RawDocument] = []
        children = payload.get("data", {}).get("children", [])
        for child in children:
            d = child.get("data", {})
            created = d.get("created_utc")
            published = ""
            if isinstance(created, (int, float)):
                from datetime import datetime

                published = datetime.fromtimestamp(created, tz=UTC).isoformat()
            docs.append(
                RawDocument(
                    source="reddit",
                    source_id=d.get("id", d.get("name", "")),
                    title=normalize_text(d.get("title", "")),
                    text=normalize_text(d.get("selftext", "")),
                    url="https://reddit.com" + d.get("permalink", "")
                    if d.get("permalink")
                    else d.get("url", ""),
                    author=d.get("author", ""),
                    published_at=published,
                    raw={"subreddit": d.get("subreddit", ""), "score": d.get("score", 0)},
                )
            )
        return docs
