"""Email newsletter generator (Layer 9).

Structure: title + subtitle + a section per top item + footer. Accepts either a
single node or a node carrying an ``items`` list of the top-ranked entries.
"""

from __future__ import annotations

from typing import Any

from content_factory.generators.base_generator import BaseContentGenerator
from utils.logger import get_logger

_log = get_logger(__name__)


class NewsletterGenerator(BaseContentGenerator):
    """Generate email newsletter content."""

    format_name = "newsletter"

    def format_item(self, node: dict[str, Any], rank: int) -> str:
        name = node.get("name", node.get("id", f"Item {rank}"))
        summary = node.get("summary", "")
        return f"{rank}. {name}\n   {summary}".rstrip()

    def generate(
        self,
        node: dict[str, Any],
        platform: str = "newsletter",
        template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        items = node.get("items") or [node]
        sections = [self.format_item(item, i + 1) for i, item in enumerate(items[:5])]
        title = (template or {}).get("title", "Your Weekly Digest")
        subtitle = (template or {}).get("subtitle", "The top stories we picked for you")
        footer = "You are receiving this because you subscribed. Unsubscribe anytime."
        body = f"{subtitle}\n\n" + "\n\n".join(sections) + f"\n\n---\n{footer}"
        content: dict[str, Any] = {
            "title": title,
            "subtitle": subtitle,
            "body": body,
            "tags": node.get("tags", []),
            "hashtags": [],
            "cta": "Forward this to a friend!",
        }
        return self._finalize(content)

    def validate_length(self, content: dict[str, Any], platform: str = "newsletter") -> bool:
        max_chars = self.constraints_for(platform).get("max_chars", 50000)
        return content.get("char_count", len(content.get("body", ""))) <= max_chars
