"""Canonical raw-document schema shared by all collectors (Layer 1 output)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from utils.helpers import content_hash, utcnow_iso


@dataclass
class RawDocument:
    """A single collected item before normalization.

    ``freshness_score`` (QA-005) is computed downstream by the time engine; the
    collector only records ``published_at`` so age can be derived later.
    """

    source: str  # platform_id, e.g. "rss"
    source_id: str  # stable id within the source
    title: str
    text: str
    url: str = ""
    author: str = ""
    language: str = ""  # filled by language_detector
    published_at: str = ""  # ISO-8601 if known
    collected_at: str = field(default_factory=utcnow_iso)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        """Exact-duplicate key based on title + text."""
        return content_hash(f"{self.title}\n{self.text}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
