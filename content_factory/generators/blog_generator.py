"""Blog content generator.

LLM: OpenAI GPT-4o-mini (Korean-optimized, low cost), lazy-imported.
Fallback: deterministic template generation when the monthly budget is
exceeded or the API/key is unavailable — keeps the pipeline working offline.
"""

from __future__ import annotations

import os
from typing import Any

from content_factory.generators.base_generator import BaseContentGenerator, estimate_tokens
from utils.logger import get_logger

_log = get_logger(__name__)

EMOTION_EMOJI: dict[str, str] = {
    "joy": "😊",
    "anger": "😤",
    "fear": "😨",
    "sadness": "😢",
    "surprise": "😲",
    "disgust": "🤢",
    "unknown": "📝",
}

PLATFORM_MAX_CHARS: dict[str, int] = {
    "naver_blog": 10_000,
    "wordpress": 20_000,
    "blog": 20_000,
    "default": 5_000,
}


class BlogGenerator(BaseContentGenerator):
    """Blog post generator (LLM + template fallback)."""

    format_name = "blog"
    MODEL = "gpt-4o-mini"
    MAX_TOKENS = 1500
    TEMPERATURE = 0.7
    # gpt-4o-mini: ~$0.001 per request average → 10,000/mo ≈ $10
    COST_PER_CALL_USD = 0.001

    def __init__(self) -> None:
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._budget_usd = float(os.getenv("OPENAI_MONTHLY_BUDGET_USD", "10.0"))
        self._cost_this_month: float = 0.0  # in-memory (resets on restart)

    def _budget_ok(self) -> bool:
        return self._cost_this_month + self.COST_PER_CALL_USD <= self._budget_usd

    def build_prompt(self, node: dict[str, Any], template: dict | None) -> str:
        emotion = node.get("emotion", "unknown")
        emoji = EMOTION_EMOJI.get(emotion, "📝")
        label = node.get("label") or node.get("name", "")
        return (
            "당신은 한국어 콘텐츠 마케터입니다.\n"
            f"주제: {label}\n"
            f"감정: {emotion} {emoji}\n"
            f"키워드: {', '.join(node.get('tags', [])[:5])}\n\n"
            "다음 구조로 블로그 포스트를 작성해주세요:\n"
            "1. 제목 (50자 이내, 감정 유발)\n"
            "2. 리드 문단 (100자, 핵심 요약)\n"
            "3. 본문 섹션 3개 (각 200자, H2 제목 포함)\n"
            "4. CTA (30자, 구독/공유 유도)\n"
            "5. 해시태그 5개\n\n"
            "응답 형식: JSON {'title': ..., 'body': ..., 'cta': ..., 'hashtags': [...]}"
        )

    async def call_llm(self, prompt: str) -> str:
        """Call GPT-4o-mini (lazy import, budget-gated)."""
        if not self._api_key or not self._budget_ok():
            return ""
        try:
            from openai import AsyncOpenAI  # lazy

            client = AsyncOpenAI(api_key=self._api_key)
            resp = await client.chat.completions.create(
                model=self.MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.MAX_TOKENS,
                temperature=self.TEMPERATURE,
            )
            self._cost_this_month += self.COST_PER_CALL_USD
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            _log.warning("llm_call_failed", extra={"error": str(exc)})
            return ""

    def _template_fallback(self, node: dict[str, Any]) -> dict[str, Any]:
        """Template-based generation (no LLM)."""
        emotion = node.get("emotion", "unknown")
        emoji = EMOTION_EMOJI.get(emotion, "📝")
        label = node.get("label") or node.get("name", "주제")
        tags = node.get("tags", [])
        title = f"{emoji} {label} 완전 분석 — 알아야 할 모든 것"
        body = (
            f"## {label}이란?\n\n"
            f"{label}에 대한 최신 트렌드와 핵심 정보를 정리했습니다.\n\n"
            "## 왜 중요한가?\n\n"
            f"현재 {label}은 많은 주목을 받고 있습니다. "
            f"특히 {', '.join(tags[:3])} 측면에서 중요한 변화가 있습니다.\n\n"
            "## 앞으로의 전망\n\n"
            f"전문가들은 {label}의 지속적인 성장을 예측하고 있습니다."
        )
        return {
            "title": title[:50],
            "body": body,
            "cta": "구독하고 최신 트렌드를 놓치지 마세요!",
            "hashtags": [f"#{t}" for t in tags[:5]],
            "generator": "template",
        }

    def generate(
        self,
        node: dict[str, Any],
        platform: str,
        template: dict | None = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper around :meth:`generate_async`."""
        import asyncio

        return asyncio.run(self.generate_async(node, platform, template))

    async def generate_async(
        self,
        node: dict[str, Any],
        platform: str,
        template: dict | None = None,
    ) -> dict[str, Any]:
        """Asynchronous blog generation."""
        prompt = self.build_prompt(node, template)
        llm_output = await self.call_llm(prompt)

        if llm_output:
            try:
                import json

                parsed = json.loads(llm_output)
                parsed["generator"] = "llm"
                parsed["llm_cost_usd"] = self.COST_PER_CALL_USD
            except json.JSONDecodeError:
                parsed = self._template_fallback(node)
        else:
            parsed = self._template_fallback(node)

        max_chars = PLATFORM_MAX_CHARS.get(platform, PLATFORM_MAX_CHARS["default"])
        parsed["body"] = parsed.get("body", "")[:max_chars]
        parsed["platform"] = platform
        parsed["format"] = "blog"
        parsed["tags"] = node.get("tags", [])
        parsed["char_count"] = len(parsed.get("body", ""))
        parsed["token_count"] = estimate_tokens(parsed.get("body", ""))
        return parsed

    def validate_length(self, content: dict[str, Any], platform: str) -> bool:
        max_chars = PLATFORM_MAX_CHARS.get(platform, PLATFORM_MAX_CHARS["default"])
        return len(content.get("body", "")) <= max_chars
