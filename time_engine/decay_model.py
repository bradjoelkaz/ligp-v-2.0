"""Time-decay model (DD-009 / QA-017).

decay(Δt) = exp(-λ · Δt_days),  λ = ln(2) / half_life_days

``half_life_days`` is taken from ``config/weights.yaml -> decay`` and may be
overridden per content type via an optional ``half_life_by_type`` mapping.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_DECAY: dict[str, Any] = {
    "half_life_days": 7,
    "lambda_default": math.log(2) / 7,
    "freshness_base": 0.5,
    "freshness_window_days": 7,
    "half_life_by_type": {},
}


@lru_cache(maxsize=1)
def _decay_config() -> dict[str, Any]:
    try:
        cfg = load_config("weights").get("decay")
        return {**_FALLBACK_DECAY, **cfg} if cfg else dict(_FALLBACK_DECAY)
    except Exception:  # pragma: no cover
        return dict(_FALLBACK_DECAY)


class DecayModel:
    """Exponential decay with per-content-type half-life support."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or _decay_config()
        self.default_half_life = float(self.config.get("half_life_days", 7))
        self.half_life_by_type = self.config.get("half_life_by_type", {}) or {}

    def _half_life(self, content_type: str) -> float:
        return float(self.half_life_by_type.get(content_type, self.default_half_life))

    def _lambda(self, content_type: str) -> float:
        half_life = self._half_life(content_type)
        return math.log(2) / half_life if half_life > 0 else 0.0

    @staticmethod
    def _age_days(created_at: datetime, now: datetime | None = None) -> float:
        ref = now or datetime.now(tz=UTC)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=UTC)
        return max(0.0, (ref - created_at).total_seconds() / 86400.0)

    def compute_decay(
        self, created_at: datetime, content_type: str = "default", now: datetime | None = None
    ) -> float:
        """Return the decay multiplier in (0, 1]."""
        lam = self._lambda(content_type)
        age = self._age_days(created_at, now)
        return math.exp(-lam * age)

    def apply_decay_to_score(
        self,
        score: float,
        created_at: datetime,
        content_type: str = "default",
        now: datetime | None = None,
    ) -> float:
        """Apply decay multiplier to a raw score."""
        return score * self.compute_decay(created_at, content_type, now)
