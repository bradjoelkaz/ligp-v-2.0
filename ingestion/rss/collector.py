"""RSS collector (Layer 1). Uses ``feedparser`` if available, else stdlib XML.

RSS / official APIs only — this satisfies the compliance constraint that we do
not scrape sites that disallow it (QA-003).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ingestion.base_collector import BaseCollector, CollectorConfig
from ingestion.schema import RawDocument
from utils.helpers import normalize_text
from utils.logger import get_logger

_log = get_logger(__name__)


class RSSCollector(BaseCollector):
    """Fetch and parse RSS/Atom feeds.

    ``fetch`` accepts ``feed_url`` (and is also given the raw XML directly via
    ``raw_xml`` for offline testing, avoiding any network dependency).
    """

    def __init__(self, config: CollectorConfig | None = None, feeds: list[str] | None = None):
        super().__init__(config or CollectorConfig(platform_id="rss", api_quota_per_day=100000))
        self.feeds = feeds or []

    async def fetch(
        self, feed_url: str | None = None, raw_xml: str | None = None, **_: Any
    ) -> list[dict[str, Any]]:
        if raw_xml is None:
            raw_xml = await self._download(feed_url)
        return [d.to_dict() for d in self.parse(raw_xml, feed_url or "")]

    async def _download(self, feed_url: str | None) -> str:
        if not feed_url:
            raise ValueError("feed_url or raw_xml is required")
        try:
            import httpx  # lazy import; optional dependency
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for live RSS fetches") from exc
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": "iigp/2.0"})
            resp.raise_for_status()
            return resp.text

    @staticmethod
    def parse(raw_xml: str, feed_url: str = "") -> list[RawDocument]:
        """Parse RSS 2.0 or Atom XML into RawDocuments (stdlib, no network)."""
        try:
            import feedparser  # type: ignore

            parsed = feedparser.parse(raw_xml)
            docs: list[RawDocument] = []
            for e in parsed.entries:
                docs.append(
                    RawDocument(
                        source="rss",
                        source_id=getattr(e, "id", getattr(e, "link", "")) or e.get("title", ""),
                        title=normalize_text(e.get("title", "")),
                        text=normalize_text(e.get("summary", "")),
                        url=e.get("link", ""),
                        author=e.get("author", ""),
                        published_at=e.get("published", ""),
                        raw={"feed": feed_url},
                    )
                )
            return docs
        except ImportError:
            return RSSCollector._parse_stdlib(raw_xml, feed_url)

    @staticmethod
    def _parse_stdlib(raw_xml: str, feed_url: str) -> list[RawDocument]:
        docs: list[RawDocument] = []
        root = ET.fromstring(raw_xml)
        # RSS 2.0: channel/item ; Atom: {ns}entry
        items = root.findall(".//item")
        atom_ns = "{http://www.w3.org/2005/Atom}"
        if not items:
            items = root.findall(f".//{atom_ns}entry")

        for item in items:

            def _text(tag: str, item=item) -> str:
                node = item.find(tag)
                if node is None:
                    node = item.find(f"{atom_ns}{tag}")
                return normalize_text(node.text) if node is not None and node.text else ""

            link_node = item.find("link")
            link = ""
            if link_node is not None:
                link = link_node.text or link_node.get("href", "") or ""

            title = _text("title")
            text = _text("description") or _text("summary") or _text("content")
            docs.append(
                RawDocument(
                    source="rss",
                    source_id=_text("guid") or link or title,
                    title=title,
                    text=text,
                    url=link,
                    author=_text("author"),
                    published_at=_text("pubDate") or _text("updated"),
                    raw={"feed": feed_url},
                )
            )
        return docs
