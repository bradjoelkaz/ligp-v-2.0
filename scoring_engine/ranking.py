"""Final candidate ranking (Layer 7).

Combines GraphScore, RevenueScore and ProbabilityScore into a single ranking
score, drops candidates below ``thresholds.yaml -> score.min_graph_score`` and
returns the top-K.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_MIN_GRAPH_SCORE = 0.35
# Blend weights for the three score families; configurable, sums to 1.0.
_BLEND = {"graph": 0.4, "revenue": 0.4, "probability": 0.2}


@lru_cache(maxsize=1)
def _min_graph_score() -> float:
    try:
        return float(load_config("thresholds").get("score", {}).get("min_graph_score", 0.35))
    except Exception:  # pragma: no cover
        return _FALLBACK_MIN_GRAPH_SCORE


class Ranker:
    """Blend score families and rank candidates."""

    def __init__(self, blend: dict[str, float] | None = None, min_graph_score: float | None = None):
        self.blend = blend or dict(_BLEND)
        self.min_graph_score = (
            min_graph_score if min_graph_score is not None else _min_graph_score()
        )

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        if not values:
            return []
        lo, hi = min(values), max(values)
        if hi == lo:
            return [0.0 for _ in values]
        return [(v - lo) / (hi - lo) for v in values]

    def rank(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach ``final_score`` (blended, normalized) and sort descending."""
        if not candidates:
            return []
        g = self._normalize([float(c.get("score", c.get("graph_score", 0.0))) for c in candidates])
        r = self._normalize([float(c.get("revenue_score", 0.0)) for c in candidates])
        p = self._normalize([float(c.get("probability_score", 0.0)) for c in candidates])
        for i, c in enumerate(candidates):
            c["final_score"] = (
                self.blend["graph"] * g[i]
                + self.blend["revenue"] * r[i]
                + self.blend["probability"] * p[i]
            )
        candidates.sort(key=lambda c: c["final_score"], reverse=True)
        return candidates

    def filter_below_threshold(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove candidates whose graph score is below the configured minimum."""
        return [
            c
            for c in candidates
            if float(c.get("score", c.get("graph_score", 0.0))) >= self.min_graph_score
        ]

    def top_k(self, ranked: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        """Return the first ``k`` ranked candidates."""
        return ranked[: max(0, k)]
