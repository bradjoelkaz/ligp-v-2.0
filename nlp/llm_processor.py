"""Gemini & OpenRouter LLM processor for clustering, analyzing, and generating prompts (Layer 12).

:class:`GeminiProcessor` takes a batch of normalized documents and asks an LLM
to cluster them into trending topics with commercial/copyright metadata plus a
Suno AI music prompt and a Google Nano Banana album-cover image prompt. It is
built with three layers of fallback so the pipeline never hard-fails:

1. **OpenRouter** chat completions (when ``OPENROUTER_API_KEY`` is set).
2. **Gemini official SDK** (``google.generativeai``) when available + keyed.
3. **Gemini HTTP API** via ``httpx`` (no SDK dependency required).

If every remote path is unavailable or returns unparsable output, a
deterministic heuristic :meth:`_mock_fallback` builds plausible topic cards from
the collected documents so the dashboard always renders something useful.
"""

from __future__ import annotations

import json
import os
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


class GeminiProcessor:
    """Cluster + analyze documents into trending topics via LLM (with fallbacks)."""

    def __init__(self, model_name: str = "gemini-1.5-flash") -> None:
        self.model_name = model_name
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

    # ----------------------------------------------------------------- #
    # Remote backends
    # ----------------------------------------------------------------- #
    def _call_openrouter(self, prompt: str) -> str:
        if not self.openrouter_key:
            return ""
        model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/bradjoelkaz/ligp-v-2.0",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        try:
            _log.info("calling_openrouter_api", extra={"model": model})
            import httpx  # lazy

            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
            return ""
        except Exception as exc:  # noqa: BLE001
            _log.warning("openrouter_call_failed", extra={"error": str(exc)})
            return ""

    def _call_gemini_sdk(self, prompt: str) -> str:
        if not self.api_key:
            return ""
        try:
            import google.generativeai as genai  # lazy, optional dependency

            _log.info("calling_gemini_sdk", extra={"model": self.model_name})
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                self.model_name,
                generation_config={"response_mime_type": "application/json"},
            )
            response = model.generate_content(prompt)
            return response.text
        except Exception as exc:  # noqa: BLE001
            _log.warning("gemini_sdk_failed_falling_back", extra={"error": str(exc)})
            return ""

    def _call_gemini_http(self, prompt: str) -> str:
        if not self.api_key:
            return ""
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent?key={self.api_key}"
        )
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        try:
            _log.info("calling_gemini_http_direct")
            import httpx  # lazy

            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
            return ""
        except Exception as exc:  # noqa: BLE001
            _log.error("gemini_http_failed", extra={"error": str(exc)})
            return ""

    # ----------------------------------------------------------------- #
    # Public API
    # ----------------------------------------------------------------- #
    def analyze_trends(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Cluster ``documents`` into 3-5 trending topics with analysis fields."""
        if not documents:
            return {"topics": []}
        if not self.openrouter_key and not self.api_key:
            _log.warning("no_llm_api_keys_unset_using_mock_fallback")
            return self._mock_fallback(documents)

        docs_str = ""
        for i, doc in enumerate(documents[:25]):
            docs_str += (
                f"Doc ID: doc_{i}\n"
                f"Source: {doc.get('platform', 'unknown')}\n"
                f"Title: {doc.get('title', '')}\n"
                f"Body: {doc.get('text', '')[:200]}\n---\n"
            )

        prompt = f"""
You are an expert news analyst. Cluster the following documents into 3 to 5 distinct trending topics/events.
For each topic, analyze and provide:
1. title: A punchy and professional Korean title.
2. category: Categorize the topic. Must choose one from: 'IT/테크', '사회/종합', '비즈니스', '문화/라이프'.
3. summary: A 3-sentence summary in Korean explaining what the issue is about.
4. entities: A list of key entities extracted from the articles (Person, Organization, Location, Concept). Format as {{"name": "...", "type": "..."}}.
5. trend_score: A float in range [0.0, 1.0].
6. velocity: A string representing the growth rate (e.g. "+35%/24h", "+12%/24h").
7. acceleration: A string representing the acceleration status (e.g. "급상승", "상승", "유지").
8. expected_revenue: A string representing estimated RPM per 10k views (e.g. "$4.82", "$3.50") based on commercial value.
9. copyright_risk: A float in range [0.0, 1.0] representing estimated safety against copy-pasting/copyright constraints (0 = safe, 1 = high risk).
10. suno_prompt: A string in English. A detailed style prompt for Suno AI music containing genre, mood tags, instruments, and BPM. Format: [Genre] mood tags, instruments, BPM. Do NOT write lyrics.
11. image_prompt: A string in English. A detailed image prompt for Google Nano Banana (Gemini image) generation, creating album artwork that matches the topic's mood. Focus on artistic style, mood, and lighting. Avoid any text in the image.

Respond strictly with a JSON object conforming to the following JSON schema:
{{
  "topics": [
    {{
      "title": "string (Korean)",
      "category": "string (Choose only from 'IT/테크', '사회/종합', '비즈니스', '문화/라이프')",
      "summary": "string (Korean)",
      "entities": [
        {{"name": "string", "type": "string"}}
      ],
      "trend_score": float,
      "velocity": "string",
      "acceleration": "string",
      "expected_revenue": "string",
      "copyright_risk": float,
      "suno_prompt": "string (English)",
      "image_prompt": "string (English)"
    }}
  ]
}}

Here are the documents to analyze:
{docs_str}
"""
        text_resp = (
            self._call_openrouter(prompt)
            or self._call_gemini_sdk(prompt)
            or self._call_gemini_http(prompt)
        )
        if not text_resp:
            return self._mock_fallback(documents)

        try:
            cleaned = self._strip_code_fence(text_resp)
            return json.loads(cleaned)
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "llm_json_parse_failed",
                extra={"response": text_resp[:500], "error": str(exc)},
            )
            return self._mock_fallback(documents)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """Strip a leading ```json / ``` code fence if the model added one."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                # Drop the opening fence and a trailing fence if present.
                body = lines[1:]
                if body and body[-1].strip().startswith("```"):
                    body = body[:-1]
                text = "\n".join(body)
        return text.strip()

    # ----------------------------------------------------------------- #
    # Heuristic fallback
    # ----------------------------------------------------------------- #
    # Category -> (suno music prompt, nano banana album-cover prompt)
    _PROMPT_HEURISTICS: dict[str, tuple[str, str]] = {
        "IT/테크": (
            "[LoFi] relaxing synth chords, chill laptop keys, soft beat, "
            "focused late-night coding mood, 75 BPM",
            "A pixel-art cozy room at night, a workspace with dual monitors, "
            "rain on the window, warm desk lamp, lo-fi aesthetic, no text",
        ),
        "비즈니스": (
            "[Acoustic] warm guitar strumming, optimistic piano chords, "
            "driving beat, morning-walk energy, 110 BPM",
            "A modern clean corporate lounge with large windows, bright sunny "
            "morning light, minimalist design, soft shadows, no text",
        ),
        "사회/종합": (
            "[Cinematic] dramatic orchestral strings, heavy percussion, "
            "melancholic oboe, epic documentary atmosphere, 90 BPM",
            "A bustling city square with a diverse crowd under a moody twilight "
            "sky, high-angle documentary shot, cinematic lighting, no text",
        ),
        "문화/라이프": (
            "[Ambient] dreamy synthesizer pads, celestial echo, acoustic harp, "
            "healing meditation-space vibe, 60 BPM",
            "A peaceful zen garden at sunset, cherry blossoms falling on still "
            "water, soft warm light, calm atmospheric art, no text",
        ),
    }

    def _mock_fallback(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        topics: list[dict[str, Any]] = []
        categories = ["IT/테크", "사회/종합", "비즈니스", "문화/라이프"]
        for i, doc in enumerate(documents[:3]):
            title = doc.get("title", "글로벌 핫 뉴스")
            category = categories[i % len(categories)]
            suno, image = self._PROMPT_HEURISTICS[category]
            topics.append(
                {
                    "title": f"[실시간] {title}",
                    "category": category,
                    "summary": (
                        f"이 이슈는 {doc.get('platform')} 뉴스 피드에서 수집된 '{title}' "
                        "주제와 깊은 연관이 있습니다. 글로벌 트렌드 추적기에 따라 신속하게 "
                        "분석된 트렌드입니다."
                    ),
                    "entities": [
                        {"name": doc.get("platform", "뉴스 포털"), "type": "Organization"},
                        {"name": "인터넷 트렌드", "type": "Concept"},
                    ],
                    "trend_score": round(0.9 - (i * 0.15), 2),
                    "velocity": f"+{20 - i * 5}%/24h",
                    "acceleration": "급상승" if i == 0 else "상승",
                    "expected_revenue": f"${4.50 - i * 0.80:.2f}",
                    "copyright_risk": round(0.15 + (i * 0.1), 2),
                    "suno_prompt": suno,
                    "image_prompt": image,
                }
            )
        if not topics:
            topics.append(
                {
                    "title": "실시간 수집된 트렌드가 없습니다",
                    "category": "사회/종합",
                    "summary": "현재 수집된 데이터가 없습니다. 수집 설정을 확인해 주십시오.",
                    "entities": [],
                    "trend_score": 0.0,
                    "velocity": "0%",
                    "acceleration": "유지",
                    "expected_revenue": "$0.00",
                    "copyright_risk": 0.0,
                    "suno_prompt": "[Ambient] silence, empty void pads, 0 BPM",
                    "image_prompt": (
                        "An empty canvas with a single grey dot in the center, "
                        "minimalist concept art, no text"
                    ),
                }
            )
        return {"topics": topics}
