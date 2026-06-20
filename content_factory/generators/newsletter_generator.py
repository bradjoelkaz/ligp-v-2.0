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

    # -- Phase 12: rich daily digest (HTML + Markdown) -----------------------

    def build_digest(
        self,
        topics: list[dict[str, Any]],
        *,
        title: str = "IIGP 데일리 트렌드 다이제스트",
        subtitle: str = "오늘 선별된 고가치 토픽 요약",
        english: bool = False,
    ) -> dict[str, Any]:
        """Assemble selected topics into a newsletter (HTML + Markdown).

        When ``english`` is True, prefer ``title_en``/``summary_en`` fields
        (populated by :class:`nlp.translator.Translator`) and fall back to the
        Korean originals when a translation is absent.
        """
        topics = topics or []

        def _t(topic: dict[str, Any]) -> str:
            return (topic.get("title_en") if english else None) or topic.get("title", "")

        def _s(topic: dict[str, Any]) -> str:
            return (topic.get("summary_en") if english else None) or topic.get("summary", "")

        md_lines = [f"# {title}", "", f"_{subtitle}_", ""]
        html_parts = [
            f"<h1>{_esc(title)}</h1>",
            f"<p style='color:#667'>{_esc(subtitle)}</p>",
            "<hr/>",
        ]
        for i, topic in enumerate(topics[:10], 1):
            t, s = _t(topic), _s(topic)
            cat = topic.get("category", "")
            md_lines += [f"## {i}. {t}", f"> {cat}", "", s, ""]
            html_parts.append(
                f"<h2>{i}. {_esc(t)}</h2>"
                f"<div style='color:#888;font-size:13px'>{_esc(cat)}</div>"
                f"<p>{_esc(s)}</p>"
            )
        footer = "구독해 주셔서 감사합니다. 언제든 수신을 해지하실 수 있습니다."
        md_lines += ["---", footer]
        html_parts.append(f"<hr/><p style='color:#aaa;font-size:12px'>{_esc(footer)}</p>")

        markdown = "\n".join(md_lines)
        html = (
            "<div style='font-family:sans-serif;max-width:640px;margin:auto'>"
            + "".join(html_parts)
            + "</div>"
        )
        content: dict[str, Any] = {
            "title": title,
            "subject": f"[{len(topics[:10])}개 토픽] {title}",
            "subtitle": subtitle,
            "format": "newsletter",
            "platform": "newsletter",
            "html": html,
            "markdown": markdown,
            "body": markdown,
            "item_count": len(topics[:10]),
            "language": "en" if english else "ko",
        }
        return self._finalize(content)


def _esc(text: str) -> str:
    """Minimal HTML escaping for newsletter assembly."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
