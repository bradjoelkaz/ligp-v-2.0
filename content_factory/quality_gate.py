"""Content quality gate (QA-024).

Four stages:
  1. Format/length validation against platform constraints.
  2. Readability score (textstat lazy; word/sentence heuristic fallback).
  3. Brand safety (banned-term list + copyright scorer).
  4. Optional LLM self-critique (lazy, budget-gated; skipped offline).

``check`` returns ``(passed, issues)``; it passes only when stages 1-3 raise no
issues.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from compliance.copyright_scorer import CopyrightScorer
from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_DEFAULT_BANNED = {"guaranteed profit", "miracle cure", "get rich quick", "100% safe", "clickbait"}
_SENT_RE = re.compile(r"[.!?]+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


@lru_cache(maxsize=1)
def _quality_config() -> dict[str, Any]:
    try:
        return load_config("thresholds").get("quality_gate", {})
    except Exception:  # pragma: no cover
        return {}


def flesch_kincaid_reading_ease(text: str) -> float:
    """Approximate Flesch reading-ease (0-100, higher = easier)."""
    words = _WORD_RE.findall(text)
    sentences = [s for s in _SENT_RE.split(text) if s.strip()]
    n_words = len(words)
    n_sentences = max(1, len(sentences))
    if n_words == 0:
        return 0.0
    syllables = sum(_count_syllables(w) for w in words)
    words_per_sentence = n_words / n_sentences
    syllables_per_word = syllables / n_words
    score = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
    return max(0.0, min(100.0, score))


def _count_syllables(word: str) -> int:
    word = word.lower()
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


class QualityGate:
    """Multi-stage content quality checker."""

    def __init__(self, banned_terms: set[str] | None = None) -> None:
        cfg = _quality_config()
        self.readability_min = float(cfg.get("gate3_readability", {}).get("blog_min", 60))
        self.banned_terms = banned_terms or set(_DEFAULT_BANNED)
        self.copyright = CopyrightScorer()

    def stage1_format(self, content: dict[str, Any], platform: str) -> list[str]:
        issues: list[str] = []
        body = content.get("body", "")
        if not body.strip():
            issues.append("empty body")
        if not content.get("title", "").strip():
            issues.append("missing title")
        try:
            constraints = load_config("platforms")
            cmap = {
                p["platform_id"]: p.get("content_constraints", {})
                for p in constraints.get("platforms", [])
            }
            max_chars = cmap.get(platform, {}).get("max_chars")
        except Exception:  # pragma: no cover
            max_chars = None
        if max_chars and len(body) > max_chars:
            issues.append(f"body exceeds max_chars ({len(body)} > {max_chars})")
        return issues

    def stage2_readability(self, content: dict[str, Any]) -> float:
        try:  # pragma: no cover - optional dependency
            import textstat

            return float(textstat.flesch_reading_ease(content.get("body", "")))
        except Exception:
            return flesch_kincaid_reading_ease(content.get("body", ""))

    def stage3_brand_safety(self, content: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        body_low = content.get("body", "").lower()
        for term in self.banned_terms:
            if term in body_low:
                issues.append(f"banned term: '{term}'")
        risk = self.copyright.score(
            content.get("body", ""), content.get("source_url", ""), content.get("license")
        )
        if not self.copyright.is_safe(risk):
            issues.append(f"copyright risk too high ({risk:.2f})")
        return issues

    def stage4_llm_critique(self, content: dict[str, Any]) -> list[str]:  # pragma: no cover
        """Optional LLM self-critique; no-op offline / without budget."""
        return []

    def check(self, content: dict[str, Any], platform: str) -> tuple[bool, list[str]]:
        """Run stages 1-3; return (passed, issues)."""
        issues: list[str] = []
        issues += self.stage1_format(content, platform)
        readability = self.stage2_readability(content)
        if readability < self.readability_min:
            issues.append(f"readability {readability:.1f} < {self.readability_min}")
        issues += self.stage3_brand_safety(content)
        passed = len(issues) == 0
        _log.info(
            "quality_gate", extra={"platform": platform, "passed": passed, "issues": len(issues)}
        )
        return passed, issues
