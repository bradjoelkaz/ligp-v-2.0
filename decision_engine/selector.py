"""Thompson Sampling content selector (QA-019 / DD-010).

Selects content using Thompson Sampling over each candidate's success/failure
counts (Beta posterior), scaled by its ranking score. Enforces topic diversity
(``thresholds.yaml -> decision.diversity``) and per-platform daily quota
(``platforms.yaml``).
"""

from __future__ import annotations

import random
from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_DIVERSITY = {
    "max_channels_per_topic": 2,
    "topic_overlap_max": 0.40,
    "min_diversity_index": 0.60,
}


@lru_cache(maxsize=1)
def _decision_config() -> dict[str, Any]:
    try:
        cfg = load_config("thresholds").get("decision", {})
        return cfg if cfg else {"diversity": _FALLBACK_DIVERSITY}
    except Exception:  # pragma: no cover
        return {"diversity": _FALLBACK_DIVERSITY}


@lru_cache(maxsize=1)
def _platform_quota() -> dict[str, int]:
    try:
        platforms = load_config("platforms").get("platforms", [])
        return {p["platform_id"]: int(p.get("api_quota_per_day", 1000)) for p in platforms}
    except Exception:  # pragma: no cover
        return {}


class ThompsonSelector:
    """Exploration-aware selector with diversity and quota constraints."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        cfg = _decision_config()
        self.diversity = cfg.get("diversity", _FALLBACK_DIVERSITY)
        self.max_same_topic = int(self.diversity.get("max_channels_per_topic", 2))

    def _thompson_value(self, candidate: dict[str, Any]) -> float:
        """Beta draw from (successes, failures) scaled by the candidate score."""
        success = float(candidate.get("success", 1.0))
        fail = float(candidate.get("fail", 1.0))
        draw = self._rng.betavariate(max(success, 1e-6), max(fail, 1e-6))
        score = float(candidate.get("final_score", candidate.get("score", 1.0)))
        return draw * score

    def select(
        self, ranked_candidates: list[dict[str, Any]], platform: str, n: int
    ) -> list[dict[str, Any]]:
        """Return up to ``n`` selected candidates for ``platform``."""
        if n <= 0 or not ranked_candidates:
            return []
        scored = sorted(ranked_candidates, key=lambda c: self._thompson_value(c), reverse=True)
        diverse = self.enforce_diversity(scored, self.max_same_topic)
        limited = self.apply_quota(diverse, platform)
        return limited[:n]

    def enforce_diversity(
        self, selected: list[dict[str, Any]], max_same_topic: int = 2
    ) -> list[dict[str, Any]]:
        """Keep at most ``max_same_topic`` items per topic, preserving order."""
        counts: dict[str, int] = {}
        out: list[dict[str, Any]] = []
        for c in selected:
            topic = str(c.get("topic", c.get("topic_id", c.get("node_id", ""))))
            if counts.get(topic, 0) >= max_same_topic:
                continue
            counts[topic] = counts.get(topic, 0) + 1
            out.append(c)
        return out

    def apply_quota(self, selected: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
        """Truncate to the platform's daily quota if one is configured."""
        quota = _platform_quota().get(platform)
        if quota is None:
            return selected
        return selected[:quota]
