"""Trend velocity / acceleration detection (DD-008 / QA-011).

Velocity(t)     = (Score_t - Score_{t-24h}) / Score_{t-24h}
Acceleration(t) = Velocity_t - Velocity_{t-6h}

State classification thresholds come from ``config/thresholds.yaml -> trend``.
Pure stdlib so it runs offline and is fully unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

ScorePoint = tuple[datetime, float]

# Fallback thresholds mirror thresholds.yaml -> trend in case config is absent.
_FALLBACK_TREND: dict[str, Any] = {
    "velocity_window_hours": 24,
    "acceleration_window_hours": 6,
    "states": {
        "rising": {"velocity_gt": 0.20, "acceleration_gt": 0.0},
        "peaking": {"velocity_abs_lt": 0.05},
        "falling": {"velocity_lt": -0.10},
        "viral": {"velocity_gt": 1.00, "alert": True},
    },
    "optimal_publish": {"require_state": "rising", "acceleration_gt": 0.05},
}


@lru_cache(maxsize=1)
def _trend_config() -> dict[str, Any]:
    try:
        cfg = load_config("thresholds").get("trend")
        return cfg if cfg else dict(_FALLBACK_TREND)
    except Exception:  # pragma: no cover - config optional in tests
        return dict(_FALLBACK_TREND)


class TrendDetector:
    """Compute velocity/acceleration and classify trend state."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or _trend_config()
        self.states = self.config.get("states", _FALLBACK_TREND["states"])

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _sorted(scores: list[ScorePoint]) -> list[ScorePoint]:
        return sorted(scores, key=lambda p: p[0])

    @staticmethod
    def _value_at_or_before(scores: list[ScorePoint], target: datetime) -> float | None:
        """Return the score value at the latest timestamp <= ``target``."""
        candidate: float | None = None
        for ts, val in scores:
            if ts <= target:
                candidate = val
            else:
                break
        return candidate

    # -- core metrics ------------------------------------------------------ #
    def compute_velocity(self, scores: list[ScorePoint], window_hours: int = 24) -> float:
        """Relative change over ``window_hours`` ending at the latest point."""
        if len(scores) < 2:
            return 0.0
        ordered = self._sorted(scores)
        now_ts, now_val = ordered[-1]
        past_target = now_ts - timedelta(hours=window_hours)
        past_val = self._value_at_or_before(ordered[:-1], past_target)
        if past_val is None:
            past_val = ordered[0][1]  # fall back to earliest available
        if past_val == 0:
            return 0.0
        return (now_val - past_val) / past_val

    def compute_acceleration(self, scores: list[ScorePoint], window_hours: int = 6) -> float:
        """Change in velocity over ``window_hours`` (second derivative proxy)."""
        if len(scores) < 3:
            return 0.0
        ordered = self._sorted(scores)
        vel_window = int(self.config.get("velocity_window_hours", 24))
        v_now = self.compute_velocity(ordered, vel_window)
        cutoff = ordered[-1][0] - timedelta(hours=window_hours)
        sub = [p for p in ordered if p[0] <= cutoff]
        v_prev = self.compute_velocity(sub, vel_window) if len(sub) >= 2 else 0.0
        return v_now - v_prev

    # -- classification ---------------------------------------------------- #
    def classify_state(self, velocity: float, acceleration: float) -> str:
        """Return one of: viral | rising | falling | peaking | stable."""
        viral = self.states.get("viral", {})
        rising = self.states.get("rising", {})
        falling = self.states.get("falling", {})
        peaking = self.states.get("peaking", {})

        if "velocity_gt" in viral and velocity > viral["velocity_gt"]:
            _log.warning("viral_trend_detected", extra={"velocity": velocity})
            return "viral"
        if (
            "velocity_gt" in rising
            and velocity > rising["velocity_gt"]
            and acceleration > rising.get("acceleration_gt", 0.0)
        ):
            return "rising"
        if "velocity_lt" in falling and velocity < falling["velocity_lt"]:
            return "falling"
        if "velocity_abs_lt" in peaking and abs(velocity) < peaking["velocity_abs_lt"]:
            return "peaking"
        return "stable"

    def is_optimal_publish_window(self, velocity: float, acceleration: float) -> bool:
        """True when state is the configured optimal state with enough acceleration."""
        opt = self.config.get("optimal_publish", _FALLBACK_TREND["optimal_publish"])
        state = self.classify_state(velocity, acceleration)
        return state == opt.get("require_state", "rising") and acceleration > opt.get(
            "acceleration_gt", 0.05
        )
