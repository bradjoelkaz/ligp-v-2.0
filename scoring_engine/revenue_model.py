"""Revenue model (DD-002 / QA-015).

RevenueScore(node, platform) =
    Σ_stream ( stream_weight × stream_value(stream, platform, cpm) )
    × EmotionBoost(emotion) × (1 − RiskPenalty(risk_flags))

* stream weights come from ``weights.yaml -> revenue_stream_weights`` (sum 1.0)
* emotion boost from ``emotion_weights.yaml`` (clamped to its boost_bounds)
* risk penalty from ``weights.yaml -> risk_penalty`` component weights
* CPM seed from ``config/cpm_history.seed.json`` (live history overrides later)
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.config_loader import load_config
from utils.helpers import clamp
from utils.logger import get_logger

_log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CPM_SEED_PATH = _REPO_ROOT / "config" / "cpm_history.seed.json"

# Relative monetization value of each stream, expressed as a multiple of CPM.
_STREAM_VALUE_FACTOR = {
    "cpm_ads": 1.0,
    "affiliate": 1.5,
    "subscription": 3.0,
    "digital_product": 2.0,
}

_FALLBACK_STREAM_WEIGHTS = {
    "cpm_ads": 0.30,
    "affiliate": 0.35,
    "subscription": 0.20,
    "digital_product": 0.15,
}
_FALLBACK_RISK = {"copyright_risk": 0.40, "controversy_risk": 0.30, "saturation_risk": 0.30}
_FALLBACK_EMOTION = {
    "joy": 1.2,
    "fear": 1.4,
    "anger": 1.3,
    "surprise": 1.5,
    "sadness": 0.8,
    "neutral": 1.0,
}


@lru_cache(maxsize=1)
def _load_cpm_seed() -> dict[str, float]:
    try:
        data = json.loads(_CPM_SEED_PATH.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.get("cpm_by_platform", {}).items()}
    except Exception:  # pragma: no cover
        return {}


class RevenueModel:
    """Compute multi-stream revenue scores with emotion and risk adjustments."""

    def __init__(self) -> None:
        try:
            weights = load_config("weights")
        except Exception:  # pragma: no cover
            weights = {}
        try:
            emotions = load_config("emotion_weights")
        except Exception:  # pragma: no cover
            emotions = {}

        self.stream_weights: dict[str, float] = weights.get(
            "revenue_stream_weights", _FALLBACK_STREAM_WEIGHTS
        )
        self.risk_weights: dict[str, float] = weights.get("risk_penalty", _FALLBACK_RISK)
        self.emotion_weights: dict[str, float] = emotions.get("emotion_weights", _FALLBACK_EMOTION)
        bounds = emotions.get("boost_bounds", {"min": 0.5, "max": 1.8})
        self.boost_min = float(bounds.get("min", 0.5))
        self.boost_max = float(bounds.get("max", 1.8))
        self.cpm_seed = _load_cpm_seed()

    def estimate_cpm(self, platform: str, content_type: str = "default") -> float:
        """Return the expected CPM (USD / 1000 impressions) for a platform."""
        base = self.cpm_seed.get(platform, 1.0)
        # Content-type multipliers could be data-driven later; neutral for now.
        multiplier = {"default": 1.0}.get(content_type, 1.0)
        return base * multiplier

    def compute_emotion_boost(self, emotion: str) -> float:
        """Map an emotion label to a revenue multiplier, clamped to bounds."""
        raw = float(self.emotion_weights.get(emotion, 1.0))
        return clamp(raw, self.boost_min, self.boost_max)

    def compute_risk_penalty(self, risk_flags: list[str]) -> float:
        """Sum the weights of active risk flags; result clamped to [0, 1]."""
        penalty = sum(float(self.risk_weights.get(flag, 0.0)) for flag in risk_flags)
        return clamp(penalty, 0.0, 1.0)

    def compute(self, node_id: str, platform: str, emotion: str, risk_flags: list[str]) -> float:
        """Full revenue score for a node on a platform."""
        cpm = self.estimate_cpm(platform)
        base = sum(
            weight * cpm * _STREAM_VALUE_FACTOR.get(stream, 1.0)
            for stream, weight in self.stream_weights.items()
        )
        boost = self.compute_emotion_boost(emotion)
        penalty = self.compute_risk_penalty(risk_flags)
        score = base * boost * (1.0 - penalty)
        _log.debug(
            "revenue_computed",
            extra={"node": node_id, "platform": platform, "cpm": cpm, "score": round(score, 4)},
        )
        return score

    def batch_compute(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Annotate each item dict with a ``revenue_score`` field."""
        for item in items:
            item["revenue_score"] = self.compute(
                item.get("node_id", ""),
                item.get("platform", "blog"),
                item.get("emotion", "neutral"),
                item.get("risk_flags", []),
            )
        return items
