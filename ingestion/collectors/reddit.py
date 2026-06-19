"""Reddit collector (OAuth2 client-credentials).

Rate limit: 60 requests/min (1 req/sec). Token cached in memory and refreshed
100s before expiry.
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime
from typing import Any

from ingestion.base_collector import BaseCollector, RawDocument
from utils.logger import get_logger

_log = get_logger(__name__)


class RedditCollector(BaseCollector):
    """Reddit API collector."""

    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    BASE_URL = "https://oauth.reddit.com"
    DEFAULT_SUBREDDITS = ["korea", "investing", "technology", "worldnews"]
    RATE_LIMIT_PER_SEC = 1.0

    def __init__(self) -> None:
        super().__init__(source="reddit", rate_limit=self.RATE_LIMIT_PER_SEC)
        self._client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self._client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._user_agent = os.getenv("REDDIT_USER_AGENT", "iigp-bot/2.0")
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _auth_header(self) -> str:
        creds = f"{self._client_id}:{self._client_secret}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    async def _get_token(self) -> str:
        """Fetch an access token (auto-refresh 100s before expiry)."""
        if self._token and time.time() < self._token_expires_at - 100:
            return self._token
        if not self._client_id:
            return ""

        try:
            import httpx  # lazy

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.TOKEN_URL,
                    headers={
                        "Authorization": self._auth_header(),
                        "User-Agent": self._user_agent,
                    },
                    data={"grant_type": "client_credentials"},
                )
                resp.raise_for_status()
                data = resp.json()
                self._token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                return self._token or ""
        except Exception as exc:  # noqa: BLE001
            self._log_error("reddit_token_failed", str(exc))
            return ""

    def _parse_post(self, post_data: dict[str, Any]) -> RawDocument:
        return RawDocument(
            source="reddit",
            url=f"https://reddit.com{post_data.get('permalink', '')}",
            title=post_data.get("title", ""),
            body=post_data.get("selftext", "") or post_data.get("url", ""),
            author=post_data.get("author", ""),
            published_at=datetime.utcfromtimestamp(post_data.get("created_utc", 0)),
            lang="en",
            raw=post_data,
        )

    async def collect(  # type: ignore[override]
        self,
        subreddit: str = "korea",
        sort: str = "hot",
        limit: int = 100,
    ) -> list[RawDocument]:
        """Collect posts from a subreddit."""
        token = await self._get_token()
        if not token:
            return []

        try:
            import httpx  # lazy

            url = f"{self.BASE_URL}/r/{subreddit}/{sort}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": self._user_agent,
                    },
                    params={"limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            self._log_error("reddit_collect_failed", str(exc))
            return []

        posts = data.get("data", {}).get("children", [])
        return [self._parse_post(p["data"]) for p in posts]

    async def search(self, query: str, limit: int = 100) -> list[RawDocument]:
        """Search across Reddit."""
        token = await self._get_token()
        if not token:
            return []

        try:
            import httpx  # lazy

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/search",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": self._user_agent,
                    },
                    params={"q": query, "sort": "new", "limit": limit, "type": "link"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            self._log_error("reddit_search_failed", str(exc))
            return []

        posts = data.get("data", {}).get("children", [])
        return [self._parse_post(p["data"]) for p in posts]

    async def health_check(self) -> bool:  # type: ignore[override]
        return bool(await self._get_token())
