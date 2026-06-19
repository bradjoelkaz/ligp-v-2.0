"""Base content generator (Layer 9).

Defines the abstract interface all format-specific generators implement, plus
shared helpers for loading per-platform constraints from ``platforms.yaml`` and
estimating token counts (tiktoken lazy, with a word-based fallback).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)


@lru_cache(maxsize=1)
def _platform_constraints() -> dict[str, dict[str, Any]]:
    try:
        platforms = load_config("platforms").get("platforms", [])
        return {p["platform_id"]: p.get("content_constraints", {}) for p in platforms}
    except Exception:  # pragma: no cover
        return {}


def estimate_tokens(text: str) -> int:
    """Estimate token count (tiktoken if present, else ~0.75 words/token)."""
    if not text:
        return 0
    try:  # pragma: no cover - optional dependency
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Rough heuristic: tokens ~= words / 0.75
        return int(len(text.split()) / 0.75) + 1


class BaseContentGenerator(ABC):
    """Common scaffolding for content generators."""

    format_name: str = "base"

    def constraints_for(self, platform: str) -> dict[str, Any]:
        return _platform_constraints().get(platform, {})

    @abstractmethod
    def generate(
        self, node: dict[str, Any], platform: str, template: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Produce a content dict (title, body, tags, hashtags, cta, ...)."""

    @abstractmethod
    def validate_length(self, content: dict[str, Any], platform: str) -> bool:
        """Return True if the content satisfies the platform's length limits."""

    # -- shared helpers ---------------------------------------------------- #
    def _finalize(self, content: dict[str, Any]) -> dict[str, Any]:
        body = content.get("body", "")
        content["format"] = self.format_name
        content["char_count"] = len(body)
        content["token_count"] = estimate_tokens(body)
        return content

    def _call_llm(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call an LLM if a client is configured; otherwise template fallback.

        The fallback returns a deterministic, structured stub so the pipeline
        and tests run offline without API keys.
        """
        try:  # pragma: no cover - requires network + key
            import os

            if os.environ.get("OPENAI_API_KEY"):
                from openai import OpenAI

                client = OpenAI()
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover
            _log.warning("llm_call_failed", extra={"error": str(exc)})
        return self._offline_stub(prompt)

    @staticmethod
    def _offline_stub(prompt: str) -> str:
        return f"[generated-offline] {prompt[:120]}"
