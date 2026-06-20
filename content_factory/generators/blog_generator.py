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
            "당신은 한국어 SEO 콘텐츠 마케터입니다.\n"
            f"주제: {label}\n"
            f"감정: {emotion} {emoji}\n"
            f"키워드: {', '.join(node.get('tags', [])[:5])}\n\n"
            "위 주제로 검색엔진 상위 노출에 유리한 한국어 블로그 포스트를 작성하세요.\n"
            "요구사항:\n"
            "1. seo_title: 검색 최적화 제목 (50자 이내, 핵심 키워드 포함)\n"
            "2. summary: 메타 설명용 요약문 (120자 이내)\n"
            "3. body: 서론 + H2/H3 소제목 3개 섹션 + 결론 (마크다운)\n"
            "4. cta: 구독/공유 유도 문구 (30자 이내)\n"
            "5. tags: SEO 태그 5개 (해시 없이)\n\n"
            "반드시 다음 JSON 형식으로만 응답하세요:\n"
            '{"seo_title": "...", "title": "...", "summary": "...", '
            '"body": "...", "cta": "...", "tags": ["...", "..."]}'
        )

    def _gemini_generate(self, node: dict[str, Any]) -> dict[str, Any] | None:
        """Generate via OpenRouter/Gemini (preferred when those keys are set).

        Returns a parsed content dict, or None to fall back to OpenAI/template.
        """
        if not (os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY")):
            return None
        try:
            import json

            from nlp.llm_processor import GeminiProcessor

            raw = GeminiProcessor().complete(self.build_prompt(node, None), as_json=True)
            if not raw:
                return None
            parsed = json.loads(raw)
            parsed.setdefault("title", parsed.get("seo_title", ""))
            parsed.setdefault("tags", node.get("tags", []))
            hashtags = [f"#{t.lstrip('#')}" for t in parsed.get("tags", [])[:5]]
            parsed["hashtags"] = parsed.get("hashtags", hashtags)
            parsed["generator"] = "gemini"
            return parsed
        except Exception as exc:  # noqa: BLE001 - any failure -> fall back
            _log.warning("gemini_blog_generate_failed", extra={"error": str(exc)})
            return None

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
            "seo_title": title[:50],
            "summary": f"{label}에 대한 최신 트렌드와 핵심 정보를 한눈에 정리했습니다."[:120],
            "body": body,
            "cta": "구독하고 최신 트렌드를 놓치지 마세요!",
            "tags": tags[:5],
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
        # Prefer OpenRouter/Gemini when configured (Phase 6 real LLM wiring).
        parsed = self._gemini_generate(node)

        if parsed is None:
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
        parsed.setdefault("tags", node.get("tags", []))
        parsed.setdefault("seo_title", parsed.get("title", ""))
        parsed.setdefault("summary", "")
        parsed["char_count"] = len(parsed.get("body", ""))
        parsed["token_count"] = estimate_tokens(parsed.get("body", ""))
        return parsed

    def validate_length(self, content: dict[str, Any], platform: str) -> bool:
        max_chars = PLATFORM_MAX_CHARS.get(platform, PLATFORM_MAX_CHARS["default"])
        return len(content.get("body", "")) <= max_chars
