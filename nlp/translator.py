"""Multilingual translation pipeline (Phase 12).

Translates Korean trend/topic content into natural English for global channels
(e.g. an English newsletter) using the shared LLM backend
(:class:`nlp.llm_processor.GeminiProcessor`). Results are attached to the topic
as ``*_en`` fields without mutating the originals destructively.

Resilient: with no API key or on any failure, translation is a safe pass-through
(English fields fall back to the source text, ``translated=False``) so the
pipeline never breaks and tests run offline.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

GLOBAL_PLATFORMS = {"newsletter", "newsletter_en", "substack", "mailchimp", "global"}


class Translator:
    """Translate Korean text/topics to English via the LLM (with fallback)."""

    def __init__(self, processor: Any | None = None) -> None:
        self._processor = processor

    def _proc(self) -> Any:
        if self._processor is None:
            from nlp.llm_processor import GeminiProcessor

            self._processor = GeminiProcessor()
        return self._processor

    def available(self) -> bool:
        proc = self._proc()
        return bool(getattr(proc, "openrouter_key", "") or getattr(proc, "api_key", ""))

    def translate(self, text: str, target: str = "en", source: str = "ko") -> str:
        """Translate ``text`` to ``target``; return the original on miss/failure."""
        if not text or not text.strip():
            return text
        if not self.available():
            return text
        prompt = (
            f"Translate the following {source} text into natural, fluent {target}. "
            "Return ONLY the translation, no quotes or commentary.\n\n"
            f"{text}"
        )
        try:
            out = self._proc().complete(prompt)
            return out.strip() if out and out.strip() else text
        except Exception as exc:  # noqa: BLE001 - never break on translation
            _log.warning("translate_failed", extra={"error": str(exc)})
            return text

    def needs_translation(self, topic: dict[str, Any], platform: str) -> bool:
        """True when a KO topic targets a global/English platform."""
        lang = (topic.get("language") or "ko").lower()
        return lang.startswith("ko") and platform in GLOBAL_PLATFORMS

    def translate_topic(self, topic: dict[str, Any], target: str = "en") -> dict[str, Any]:
        """Return a copy of ``topic`` with ``title_en``/``summary_en`` populated.

        Sets ``translated`` to True only when the LLM actually produced output.
        """
        out = dict(topic)
        title = topic.get("title", "")
        summary = topic.get("summary", "")
        title_en = self.translate(title, target=target)
        summary_en = self.translate(summary, target=target)
        out["title_en"] = title_en
        out["summary_en"] = summary_en
        out["translated"] = bool(self.available() and (title_en != title or summary_en != summary))
        return out
