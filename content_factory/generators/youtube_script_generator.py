"""YouTube 2-column video-script generator (Layer 6, Korean).

Produces a professional scenario script for YouTube Shorts or long-form videos
as a **2-column** structure: a visual/action guide (\ud654\uba74 \uc5f0\ucd9c) alongside the narration
(\ub0b4\ub808\uc774\uc158 \ub300\uc0ac). Always opens with a <=3-second hook and closes with a
subscribe/like CTA.

Deterministic offline (no API key required) so the pipeline and tests run
without network; if an LLM client is configured the narration bodies can be
enriched via :meth:`BaseContentGenerator._call_llm`.
"""

from __future__ import annotations

from typing import Any

from content_factory.generators.base_generator import BaseContentGenerator
from utils.logger import get_logger

_log = get_logger(__name__)

# Platforms this generator handles.
SHORTS = "youtube_shorts"
LONGFORM = "youtube_long"


class YouTubeScriptGenerator(BaseContentGenerator):
    """Generate a 2-column (visual | narration) Korean YouTube script."""

    format_name = "youtube_script"

    def generate_hook(self, topic: str) -> str:
        """<=3s opening hook designed to stop the scroll."""
        return f"잠깐! '{topic}', 지금 모르면 손해입니다. 3초만 집중하세요."

    def generate_cta(self, platform: str) -> str:
        if platform == SHORTS:
            return "더 많은 정보는 구독과 좋아요! 다음 쇼츠에서 만나요."
        return "영상이 도움이 되셨다면 구독과 좋아요, 알림 설정까지 부탁드립니다!"

    def _segments(self, topic: str, summary: str, entities: list[str], platform: str):
        """Build the body segments (excluding hook/CTA) for the platform."""
        ents = ", ".join(entities[:3]) if entities else topic
        base = [
            {
                "section": "도입",
                "visual": f"'{topic}' 키워드 타이포그래피 + 관련 b-roll 인서트",
                "narration": summary or f"오늘은 '{topic}'에 대해 핵심만 빠르게 정리해 드립니다.",
            },
            {
                "section": "핵심 1",
                "visual": f"핵심 포인트 자막 강조, {ents} 로고/이미지 오버레이",
                "narration": f"먼저 알아둘 것은 {ents} 와(과) 관련된 핵심 흐름입니다.",
            },
            {
                "section": "핵심 2",
                "visual": "데이터/그래프 모션 그래픽, 숫자 카운트업 애니메이션",
                "narration": f"'{topic}'이(가) 왜 지금 중요한지, 수치와 맥락으로 짚어봅니다.",
            },
        ]
        if platform == LONGFORM:
            base.extend(
                [
                    {
                        "section": "심화",
                        "visual": "전문가 인용구 카드, 화면 분할 비교 컷",
                        "narration": f"조금 더 깊이 들어가면, '{topic}'의 배경과 향후 전망이 보입니다.",
                    },
                    {
                        "section": "정리",
                        "visual": "요점 3가지 불릿 리스트 풀스크린",
                        "narration": "지금까지의 내용을 세 가지로 요약해 정리하겠습니다.",
                    },
                ]
            )
        return base

    def _llm_generate(
        self, topic: str, summary: str, entities: list[str], platform: str
    ) -> dict[str, Any] | None:
        """Generate a richer 2-column script via OpenRouter/Gemini when keyed.

        Returns a dict with ``hook``/``cta``/``segments``/SEO fields, or None to
        fall back to the deterministic builder (offline / on any failure).
        """
        import os

        if not (os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY")):
            return None
        kind = "쇼츠(60초 이내)" if platform == SHORTS else "롱폼"
        prompt = (
            "당신은 한국어 유튜브 대본 작가입니다. 다음 주제로 "
            f"{kind} 영상의 2열 대본을 작성하세요.\n"
            f"주제: {topic}\n요약: {summary}\n키워드: {', '.join(entities[:5])}\n\n"
            "규칙: 초반 3초 훅과 마지막 구독 유도(CTA)를 반드시 포함하고, 각 구간은 화면 "
            "연출(visual)과 내레이션 대사(narration)로 구분하세요.\n"
            "반드시 다음 JSON으로만 응답:\n"
            '{"seo_title": "...", "summary": "...", "tags": ["..."], '
            '"hook": "...", "cta": "...", '
            '"segments": [{"section": "...", "visual": "...", "narration": "..."}]}'
        )
        try:
            import json

            from nlp.llm_processor import GeminiProcessor

            raw = GeminiProcessor().complete(prompt, as_json=True)
            if not raw:
                return None
            data = json.loads(raw)
            return data if data.get("segments") else None
        except Exception as exc:  # noqa: BLE001 - fall back to deterministic
            _log.warning("gemini_youtube_generate_failed", extra={"error": str(exc)})
            return None

    def generate(
        self,
        node: dict[str, Any],
        platform: str = LONGFORM,
        template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if platform not in (SHORTS, LONGFORM):
            platform = LONGFORM
        topic = node.get("title") or node.get("name") or node.get("id", "주제")
        summary = node.get("summary", "")
        entities = [e.get("name", "") for e in node.get("entities", []) if e.get("name")]

        llm = self._llm_generate(topic, summary, entities, platform)
        if llm:
            hook = llm.get("hook") or self.generate_hook(topic)
            cta = llm.get("cta") or self.generate_cta(platform)
            body_rows = [
                {
                    "section": s.get("section", "본문"),
                    "visual": s.get("visual", ""),
                    "narration": s.get("narration", ""),
                }
                for s in llm.get("segments", [])
            ]
            seo_title = llm.get("seo_title") or topic
            seo_summary = llm.get("summary") or summary
            tags = llm.get("tags") or entities[:10]
            generator = "gemini"
        else:
            hook = self.generate_hook(topic)
            cta = self.generate_cta(platform)
            body_rows = self._segments(topic, summary, entities, platform)
            seo_title = f"{topic} | 핵심 정리"
            seo_summary = summary or f"'{topic}'의 핵심을 빠르게 정리한 영상입니다."
            tags = entities[:10]
            generator = "template"

        rows: list[dict[str, str]] = [
            {
                "section": "훅(3초)",
                "visual": "강렬한 클로즈업 + 텍스트 팝업, 빠른 컷 전환",
                "narration": hook,
            }
        ]
        rows.extend(body_rows)
        rows.append(
            {"section": "CTA", "visual": "구독 버튼 애니메이션 + 채널 아트 노출", "narration": cta}
        )

        script_markdown = self._to_markdown(rows)
        content: dict[str, Any] = {
            "title": f"[{'쇼츠' if platform == SHORTS else '롱폼'}] {topic}",
            "seo_title": seo_title[:60],
            "summary": seo_summary[:120],
            "platform": platform,
            "hook": hook,
            "cta": cta,
            "segments": rows,
            "script_markdown": script_markdown,
            "body": script_markdown,
            "tags": tags,
            "generator": generator,
        }
        return self._finalize(content)

    @staticmethod
    def _to_markdown(rows: list[dict[str, str]]) -> str:
        """Render the segments as a 2-column Markdown table."""
        lines = ["| 구분 | 화면 연출 (Visual) | 내레이션 대사 (Audio) |", "| --- | --- | --- |"]
        for r in rows:
            visual = r["visual"].replace("|", "/")
            narration = r["narration"].replace("|", "/")
            lines.append(f"| {r['section']} | {visual} | {narration} |")
        return "\n".join(lines)

    def validate_length(self, content: dict[str, Any], platform: str = LONGFORM) -> bool:
        """Shorts must stay punchy; long-form allows more segments."""
        n_segments = len(content.get("segments", []))
        if platform == SHORTS:
            return 3 <= n_segments <= 6
        return 4 <= n_segments <= 12
