"""Short-form video script generator (Layer 9).

Targets YouTube Shorts / Reels / TikTok: Hook (3s) + body (45s) + CTA (12s),
roughly <= 150 words for a 60s clip. Emotion-driven hook.
"""

from __future__ import annotations

from typing import Any

from content_factory.generators.base_generator import BaseContentGenerator
from utils.logger import get_logger

_log = get_logger(__name__)

_HOOK_BY_EMOTION = {
    "surprise": "You won't believe what just happened with",
    "fear": "Here's the hidden risk in",
    "joy": "This is the best thing about",
    "anger": "Why everyone is furious about",
    "sadness": "The hard truth about",
    "disgust": "The ugly side of",
}


class ShortVideoGenerator(BaseContentGenerator):
    """Generate short video scripts."""

    format_name = "short_video"

    def generate_hook(self, node: dict[str, Any]) -> str:
        emotion = node.get("emotion", "surprise")
        topic = node.get("name", node.get("id", "this topic"))
        opener = _HOOK_BY_EMOTION.get(emotion, "Here's what you should know about")
        return f"{opener} {topic}!"

    def generate_cta(self, platform: str) -> str:
        return {
            "shorts": "Follow for daily shorts!",
            "instagram": "Save this and follow for more!",
        }.get(platform, "Like and follow for more!")

    def generate(
        self, node: dict[str, Any], platform: str = "shorts", template: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        topic = node.get("name", node.get("id", "topic"))
        hook = self.generate_hook(node)
        prompt = f"Write a 45-second punchy script body about '{topic}' for a short video."
        body_core = self._call_llm(prompt, max_tokens=300)
        cta = self.generate_cta(platform)
        body = f"{hook}\n\n{body_core}\n\n{cta}"
        content: dict[str, Any] = {
            "title": f"{topic} in 60 seconds",
            "hook": hook,
            "body": body,
            "cta": cta,
            "tags": node.get("tags", []),
            "hashtags": [f"#{t.replace(' ', '')}" for t in node.get("tags", [])][:15],
        }
        return self._finalize(content)

    def validate_length(self, content: dict[str, Any], platform: str = "shorts") -> bool:
        # ~150 words ceiling for a 60s clip.
        return len(content.get("body", "").split()) <= 160
