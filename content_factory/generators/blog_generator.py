"""Blog post generator (Layer 9).

Produces a structured blog post (H1 + lead + 3 sections + CTA + hashtags).
LLM calls are lazy via the base class; offline it falls back to a deterministic
template so the pipeline and tests run without API keys.
"""

from __future__ import annotations

from typing import Any

from content_factory.generators.base_generator import BaseContentGenerator
from utils.logger import get_logger

_log = get_logger(__name__)


class BlogGenerator(BaseContentGenerator):
    """Generate long-form blog content."""

    format_name = "blog"

    def build_prompt(self, node: dict[str, Any], template: dict[str, Any] | None) -> str:
        topic = node.get("name", node.get("id", "topic"))
        tone = (template or {}).get("tone", "informative")
        return (
            f"Write an {tone} blog post about '{topic}'. Structure: an H1 title, "
            f"a lead paragraph, three body sections with subheadings, and a closing "
            f"call to action. Keep it engaging and factual."
        )

    def call_llm(self, prompt: str) -> str:
        """Public hook used by the pipeline; delegates to the base LLM caller."""
        return self._call_llm(prompt, max_tokens=2000)

    def generate(
        self, node: dict[str, Any], platform: str = "blog", template: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        topic = node.get("name", node.get("id", "topic"))
        prompt = self.build_prompt(node, template)
        body = self.call_llm(prompt)
        tags = node.get("tags", [])
        content: dict[str, Any] = {
            "title": f"{topic}: What You Need to Know",
            "body": body,
            "tags": tags,
            "hashtags": [f"#{t.replace(' ', '')}" for t in tags][:10],
            "cta": "Subscribe for more insights like this.",
        }
        return self._finalize(content)

    def validate_length(self, content: dict[str, Any], platform: str = "blog") -> bool:
        max_chars = self.constraints_for(platform).get("max_chars", 30000)
        return content.get("char_count", len(content.get("body", ""))) <= max_chars
