"""GraphScore computation (QA-017 / DD-002).

GraphScore = w_edge·norm(edge_sum) + w_centrality·norm(centrality)
           + w_trend·norm(trend_score) + w_event·norm(event_boost)

Weights come from ``weights.yaml -> graph_score`` (sum 1.0). For a single node
the inputs are assumed already normalized to [0, 1]; ``batch_compute`` performs
the cross-candidate min-max normalization before weighting.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_COMPONENTS = ("edge_sum", "centrality", "trend_score", "event_boost")
_FALLBACK_WEIGHTS = {"w_edge": 0.30, "w_centrality": 0.25, "w_trend": 0.30, "w_event": 0.15}


@lru_cache(maxsize=1)
def _weights() -> dict[str, float]:
    try:
        cfg = load_config("weights").get("graph_score")
        return cfg if cfg else dict(_FALLBACK_WEIGHTS)
    except Exception:  # pragma: no cover
        return dict(_FALLBACK_WEIGHTS)


class GraphScoreComputer:
    """Weighted-sum GraphScore with min-max normalization."""

    def __init__(self, config: dict[str, float] | None = None) -> None:
        self.w = config or _weights()
        self.normalization = self.w.get("normalization", "minmax")

    def compute(
        self,
        node_id: str,
        edge_sum: float,
        centrality: float,
        trend_score: float,
        event_boost: float,
    ) -> float:
        """Weighted sum of already-normalized [0,1] components."""
        return (
            self.w.get("w_edge", 0.30) * edge_sum
            + self.w.get("w_centrality", 0.25) * centrality
            + self.w.get("w_trend", 0.30) * trend_score
            + self.w.get("w_event", 0.15) * event_boost
        )

    @staticmethod
    def normalize_minmax(values: list[float]) -> list[float]:
        """Min-max scale to [0, 1]; returns all-zeros if values are constant."""
        if not values:
            return []
        lo, hi = min(values), max(values)
        if hi == lo:
            return [0.0 for _ in values]
        span = hi - lo
        return [(v - lo) / span for v in values]

    def batch_compute(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize each component across the batch, then attach ``score``.

        Each candidate must carry the raw component values under the keys in
        ``_COMPONENTS``; missing values default to 0.0. The result is sorted by
        score descending.
        """
        if not candidates:
            return []
        normed: dict[str, list[float]] = {}
        for comp in _COMPONENTS:
            raw = [float(c.get(comp, 0.0)) for c in candidates]
            normed[comp] = self.normalize_minmax(raw)

        for i, cand in enumerate(candidates):
            cand["score"] = self.compute(
                cand.get("node_id", ""),
                normed["edge_sum"][i],
                normed["centrality"][i],
                normed["trend_score"][i],
                normed["event_boost"][i],
            )
        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates
