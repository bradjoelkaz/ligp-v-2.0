"""Naver Blog search collector.

API: https://developers.naver.com/docs/serviceapi/search/blog/blog.md
Rate limit: 25,000 calls/day  (~0.29 calls/sec).
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime
from typing import Any

from ingestion.base_collector import BaseCollector, RawDocument
from utils.logger import get_logger

_log = get_logger(__name__)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_HTML_TAG_RE.sub("", text)).strip()


class NaverBlogCollector(BaseCollector):
    """Naver Blog Search API collector."""

    API_URL = "https://openapi.naver.com/v1/search/blog.json"
    DISPLAY_MAX = 100

    def __init__(self) -> None:
        # 25,000 / 86,400s ~= 0.29 req/sec
        super().__init__(source="naver_blog", rate_limit=0.29)
        self._client_id = os.getenv("NAVER_CLIENT_ID", "")
        self._client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
        if not self._client_id or not self._client_secret:
            _log.warning("naver_credentials_missing")

    def _headers(self) -> dict[str, str]:
        return {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
        }

    async def collect(  # type: ignore[override]
        self,
        query: str,
        display: int = 100,
        sort: str = "date",
    ) -> list[RawDocument]:
        """Search blog posts for ``query``."""
        if not self._client_id:
            return []

        display = min(display, self.DISPLAY_MAX)
        params = {"query": query, "display": display, "sort": sort}

        try:
            import httpx  # lazy

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.API_URL, params=params, headers=self._headers())
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            self._log_error("naver_collect_failed", str(exc))
            return []

        docs: list[RawDocument] = []
        for item in data.get("items", []):
            postdate_str = item.get("postdate", "")
            try:
                published_at = datetime.strptime(postdate_str, "%Y%m%d")
            except ValueError:
                published_at = datetime.utcnow()

            docs.append(
                RawDocument(
                    source="naver_blog",
                    url=item.get("link", ""),
                    title=_strip_html(item.get("title", "")),
                    body=_strip_html(item.get("description", "")),
                    author=item.get("bloggername", ""),
                    published_at=published_at,
                    lang="ko",
                    raw=item,
                )
            )
        return docs

    async def collect_keywords(self, keywords: list[str]) -> list[RawDocument]:
        """Sequentially collect multiple keywords."""
        results: list[RawDocument] = []
        for kw in keywords:
            results.extend(await self.collect(query=kw))
        return results

    async def health_check(self) -> bool:  # type: ignore[override]
        if not self._client_id:
            return False
        docs = await self.collect(query="테스트", display=1)
        return len(docs) > 0
