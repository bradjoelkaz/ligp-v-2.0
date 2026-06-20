"""Data collectors package (Layer 1 / Layer 11).

Re-exports the synchronous feed collectors so callers can use the documented
``from ingestion.collectors import collect_all_feeds`` import path. The async
OAuth collectors remain importable from their submodules
(``ingestion.collectors.naver`` / ``ingestion.collectors.reddit``).
"""

from __future__ import annotations

from ingestion.collectors.feeds import (
    BaseFeedCollector,
    NaverAPICollector,
    RedditFeedCollector,
    RSSCollector,
    collect_all_feeds,
)

__all__ = [
    "BaseFeedCollector",
    "NaverAPICollector",
    "RedditFeedCollector",
    "RSSCollector",
    "collect_all_feeds",
]
