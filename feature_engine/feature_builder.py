"""Feature vector builder (Layer 8 / QA-013).

Assembles a flat feature dict for the scoring/ranking layers from the node and
its scoring results. Emotion is one-hot encoded into a 6-d vector; platform is
label-encoded.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

_EMOTIONS = ("joy", "anger", "fear", "sadness", "surprise", "disgust")
_PLATFORMS = ("blog", "youtube", "instagram", "shorts", "newsletter")


class FeatureBuilder:
    """Build flat feature dicts for model consumption."""

    def _emotion_vec(self, emotion: str) -> dict[str, float]:
        return {f"emotion_{e}": (1.0 if e == emotion else 0.0) for e in _EMOTIONS}

    def _platform_enc(self, platform: str) -> int:
        return _PLATFORMS.index(platform) if platform in _PLATFORMS else -1

    def build(
        self, node: dict[str, Any], scoring_results: dict[str, Any], platform: str
    ) -> dict[str, Any]:
        """Return a flat feature dict for one node/platform pair."""
        feat: dict[str, Any] = {
            "node_id": node.get("id", node.get("node_id", "")),
            "graph_score": float(scoring_results.get("graph_score", 0.0)),
            "revenue_score": float(scoring_results.get("revenue_score", 0.0)),
            "ctr_estimate": float(scoring_results.get("ctr_estimate", 0.0)),
            "velocity": float(scoring_results.get("velocity", 0.0)),
            "acceleration": float(scoring_results.get("acceleration", 0.0)),
            "decay": float(scoring_results.get("decay", 1.0)),
            "event_boost": float(scoring_results.get("event_boost", 1.0)),
            "topic_id": int(node.get("topic_id", -1)),
            "platform_enc": self._platform_enc(platform),
        }
        feat.update(self._emotion_vec(scoring_results.get("emotion", "joy")))
        return feat

    def build_batch(
        self,
        nodes: list[dict[str, Any]],
        scoring_results: list[dict[str, Any]],
        platform: str,
    ) -> list[dict[str, Any]]:
        if len(nodes) != len(scoring_results):
            raise ValueError("nodes and scoring_results must be the same length")
        return [self.build(n, s, platform) for n, s in zip(nodes, scoring_results, strict=True)]
