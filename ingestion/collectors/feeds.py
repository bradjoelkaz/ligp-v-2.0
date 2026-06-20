"""Real-time feed collectors for RSS, Reddit JSON, and Naver Search API (Layer 11).

These collectors are intentionally *synchronous* and dependency-light: they use
``httpx.Client`` directly and parse RSS via the stdlib ``xml.etree`` so they can
run inside the admin dashboard request path and the daily pipeline without an
event loop. They are distinct from the async OAuth collectors in
``ingestion/collectors/naver.py`` and ``ingestion/collectors/reddit.py`` which
are wired into the resilient ``BaseCollector`` machinery.

The public entry point is :func:`collect_all_feeds`, which fans out across the
configured Korean + global news/social sources and returns a flat list of
normalized document dicts shaped for :func:`run_daily_pipeline` and the Gemini
trend analyzer (keys: ``source_id``, ``title``, ``text``, ``source_url``,
``platform``, ``published_at``).
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Global + Korean RSS sources. Naver is handled separately (API first, RSS
# fallback) inside ``collect_all_feeds``.
DEFAULT_RSS_FEEDS: list[tuple[str, str]] = [
    ("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", "google"),
    ("https://techcrunch.com/feed/", "techcrunch"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "bbc"),
    ("https://news.ycombinator.com/rss", "hackernews"),
]

# Reddit subreddits collected via the public JSON endpoint.
DEFAULT_SUBREDDITS: list[str] = ["technology", "news"]


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse surrounding whitespace."""
    return _HTML_TAG_RE.sub("", text or "").strip()


class BaseFeedCollector:
    """Shared synchronous HTTP fetch with a browser-like User-Agent."""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

    def _fetch(self, url: str) -> str:
        """GET ``url`` and return the response body, or "" on any failure."""
        try:
            import httpx  # lazy: keep the package importable without httpx

            with httpx.Client(headers=self.headers, timeout=self.timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as exc:  # noqa: BLE001 - collectors must not crash callers
            _log.error("feed_fetch_failed", extra={"url": url, "error": str(exc)})
            return ""


class RSSCollector(BaseFeedCollector):
    """Generic RSS 2.0 collector (channel/item structure)."""

    def collect(self, url: str, source_platform: str) -> list[dict[str, Any]]:
        xml_data = self._fetch(url)
        if not xml_data:
            return []

        documents: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_data.encode("utf-8"))
            channel = root.find("channel")
            if channel is None:
                return []

            for item in channel.findall("item"):
                title_elem = item.find("title")
                desc_elem = item.find("description")
                link_elem = item.find("link")
                pub_date_elem = item.find("pubDate")

                title = title_elem.text if title_elem is not None else ""
                text = desc_elem.text if desc_elem is not None else ""
                link = link_elem.text if link_elem is not None else ""
                pub_date = pub_date_elem.text if pub_date_elem is not None else ""

                if not title and not text:
                    continue

                clean_text = _strip_html(text or "")

                documents.append(
                    {
                        "source_id": f"{source_platform}_{hash(link)}",
                        "title": title or "",
                        "text": clean_text,
                        "source_url": link or "",
                        "platform": source_platform,
                        "published_at": pub_date,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            _log.error("rss_parse_failed", extra={"url": url, "error": str(exc)})
        return documents


class RedditFeedCollector(BaseFeedCollector):
    """Reddit collector using the unauthenticated public JSON endpoint.

    Named ``RedditFeedCollector`` to avoid colliding with the OAuth-based
    :class:`ingestion.collectors.reddit.RedditCollector`.
    """

    def collect(self, subreddit: str = "news", limit: int = 10) -> list[dict[str, Any]]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        json_data = self._fetch(url)
        if not json_data:
            return []

        documents: list[dict[str, Any]] = []
        try:
            data = json.loads(json_data)
            children = data.get("data", {}).get("children", [])
            for child in children:
                post = child.get("data", {})
                title = post.get("title", "")
                text = post.get("selftext", "")
                permalink = post.get("permalink", "")
                link = f"https://www.reddit.com{permalink}"

                if not title:
                    continue

                documents.append(
                    {
                        "source_id": f"reddit_{post.get('id', hash(link))}",
                        "title": title,
                        "text": text or title,
                        "source_url": link,
                        "platform": "reddit",
                        "published_at": post.get("created_utc", ""),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            _log.error("reddit_parse_failed", extra={"subreddit": subreddit, "error": str(exc)})
        return documents


class NaverAPICollector(BaseFeedCollector):
    """Naver Search (News) API collector."""

    def __init__(self, client_id: str, client_secret: str, timeout: float = 10.0) -> None:
        super().__init__(timeout)
        self.headers.update(
            {
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            }
        )

    def collect(self, query: str = "IT", limit: int = 15) -> list[dict[str, Any]]:
        safe_query = urllib.parse.quote(query)
        url = (
            "https://openapi.naver.com/v1/search/news.json"
            f"?query={safe_query}&display={limit}&sort=sim"
        )
        try:
            import httpx  # lazy

            with httpx.Client(headers=self.headers, timeout=self.timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            _log.error("naver_api_collect_failed", extra={"query": query, "error": str(exc)})
            return []

        documents: list[dict[str, Any]] = []
        for item in data.get("items", []):
            title = item.get("title", "")
            desc = item.get("description", "")
            link = item.get("link", item.get("originallink", ""))
            pub_date = item.get("pubDate", "")

            clean_title = urllib.parse.unquote(_strip_html(title))
            clean_desc = _strip_html(desc)

            documents.append(
                {
                    "source_id": f"naver_api_{hash(link)}",
                    "title": clean_title,
                    "text": clean_desc,
                    "source_url": link,
                    "platform": "naver",
                    "published_at": pub_date,
                }
            )
        return documents


def collect_all_feeds() -> list[dict[str, Any]]:
    """Fan out across all configured sources and return normalized documents.

    Naver uses the Search API when ``NAVER_CLIENT_ID``/``NAVER_CLIENT_SECRET``
    are set, otherwise it falls back to the Naver IT/science RSS section. Google
    News, TechCrunch, BBC World, Hacker News and selected subreddits are always
    collected. Any individual source failing is logged and skipped.
    """
    rss_collector = RSSCollector()
    reddit_collector = RedditFeedCollector()

    naver_client_id = os.getenv("NAVER_CLIENT_ID", "")
    naver_client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    all_docs: list[dict[str, Any]] = []

    # --- Naver: Search API (preferred) or RSS fallback ---
    if naver_client_id and naver_client_secret:
        _log.info("using_naver_search_api_for_collection")
        naver_api = NaverAPICollector(naver_client_id, naver_client_secret)
        all_docs.extend(naver_api.collect("IT", limit=10))
        all_docs.extend(naver_api.collect("테크", limit=10))
        all_docs.extend(naver_api.collect("트렌드", limit=10))
    else:
        _log.info("using_naver_rss_fallback_for_collection")
        all_docs.extend(rss_collector.collect("https://news.naver.com/rss/section/105", "naver"))

    # --- Global / Korean RSS sources ---
    for feed_url, platform in DEFAULT_RSS_FEEDS:
        all_docs.extend(rss_collector.collect(feed_url, platform))

    # --- Reddit (public JSON) ---
    for subreddit in DEFAULT_SUBREDDITS:
        all_docs.extend(reddit_collector.collect(subreddit, limit=10))

    _log.info("collect_all_feeds_complete", extra={"raw_count": len(all_docs)})
    return all_docs
